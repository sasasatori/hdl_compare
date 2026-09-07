// i2c_master: 字节级 I2C 主控制器, 开漏 4 线建模, 支持时钟延展.
// SCL 半周期 = div clk (div>=4). 每位流程: SCL低(div, 改SDA) -> 释放SCL ->
// 等 scl_i==1 (延展) -> 高电平 div (中点采样) -> 拉低 SCL.
module i2c_master (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] div,
    input  wire        cmd_valid,
    output wire        cmd_ready,
    input  wire [1:0]  cmd_op,
    input  wire [7:0]  cmd_data,
    output reg         rsp_valid,
    output reg  [7:0]  rsp_data,
    output reg         rsp_nack,
    output wire        busy,
    output reg         scl_o,
    input  wire        scl_i,
    output reg         sda_o,
    input  wire        sda_i
);

    localparam OP_START = 2'd0, OP_WRITE = 2'd1, OP_READ = 2'd2, OP_STOP = 2'd3;

    localparam ST_IDLE    = 4'd0,
               ST_START_A = 4'd1,  // SDA 释放, SCL 维持, 建立时间
               ST_START_B = 4'd2,  // 释放 SCL, 等 scl_i 高并保持 div
               ST_START_C = 4'd3,  // SDA 拉低 (START 条件), 保持 div
               ST_LOW     = 4'd4,  // SCL 低相位 (SDA 已在进入时设好)
               ST_RISE    = 4'd5,  // 释放 SCL, 等 scl_i==1 (延展)
               ST_HIGH    = 4'd6,  // SCL 高相位, 中点采样
               ST_STOP_A  = 4'd7,  // SDA 拉低, SCL 低, 保持 div
               ST_STOP_B  = 4'd8,  // 释放 SCL, 等 scl_i 高
               ST_STOP_C  = 4'd9;  // 保持 div 后释放 SDA (STOP 条件)

    reg [3:0]  state;
    reg [1:0]  op_r;
    reg [7:0]  data_r;
    reg [3:0]  bit_idx;    // 0..7 数据位 (MSB 先), 8 = ACK 位
    reg [7:0]  rx_shift;
    reg [15:0] cnt;
    reg        nack_r;

    assign cmd_ready = (state == ST_IDLE);
    assign busy      = (state != ST_IDLE);

    wire [15:0] half     = {1'b0, div[15:1]};
    wire        cnt_done = (cnt == div - 16'd1);

    always @(posedge clk) begin
        if (rst) begin
            state    <= ST_IDLE;
            scl_o    <= 1'b1;
            sda_o    <= 1'b1;
            rsp_valid <= 1'b0;
            rsp_data <= 8'd0;
            rsp_nack <= 1'b0;
            op_r     <= 2'd0;
            data_r   <= 8'd0;
            bit_idx  <= 4'd0;
            rx_shift <= 8'd0;
            cnt      <= 16'd0;
            nack_r   <= 1'b0;
        end else begin
            rsp_valid <= 1'b0;   // 单周期脉冲
            case (state)
                ST_IDLE: begin
                    if (cmd_valid) begin
                        op_r   <= cmd_op;
                        data_r <= cmd_data;
                        cnt    <= 16'd0;
                        case (cmd_op)
                            OP_START: begin
                                sda_o <= 1'b1;      // SCL 维持原状 (重复 START 时为低)
                                state <= ST_START_A;
                            end
                            OP_WRITE: begin
                                scl_o   <= 1'b0;
                                sda_o   <= cmd_data[7];   // MSB 先
                                bit_idx <= 4'd0;
                                state   <= ST_LOW;
                            end
                            OP_READ: begin
                                scl_o   <= 1'b0;
                                sda_o   <= 1'b1;          // 释放, 从机驱动
                                bit_idx <= 4'd0;
                                state   <= ST_LOW;
                            end
                            default: begin                // OP_STOP
                                sda_o <= 1'b0;
                                state <= ST_STOP_A;
                            end
                        endcase
                    end
                end

                // ---- START ----
                ST_START_A: begin
                    if (cnt_done) begin
                        cnt   <= 16'd0;
                        scl_o <= 1'b1;
                        state <= ST_START_B;
                    end else cnt <= cnt + 16'd1;
                end
                ST_START_B: begin
                    if (scl_i) begin
                        if (cnt_done) begin
                            cnt   <= 16'd0;
                            sda_o <= 1'b0;              // SCL 高时 SDA 下降 = START
                            state <= ST_START_C;
                        end else cnt <= cnt + 16'd1;
                    end
                end
                ST_START_C: begin
                    if (cnt_done) begin
                        scl_o <= 1'b0;                  // 建立时间后拉低 SCL, 完成
                        state <= ST_IDLE;
                    end else cnt <= cnt + 16'd1;
                end

                // ---- WRITE / READ 位流 ----
                ST_LOW: begin
                    if (cnt_done) begin
                        cnt   <= 16'd0;
                        scl_o <= 1'b1;
                        state <= ST_RISE;
                    end else cnt <= cnt + 16'd1;
                end
                ST_RISE: begin
                    if (scl_i) begin                    // 含时钟延展等待
                        cnt   <= 16'd0;
                        state <= ST_HIGH;
                    end
                end
                ST_HIGH: begin
                    // SCL 高半周期中点采样
                    if (cnt == half) begin
                        if (op_r == OP_WRITE) begin
                            if (bit_idx == 4'd8)
                                nack_r <= sda_i;        // ACK 位: 0=ACK
                        end else begin
                            if (bit_idx < 4'd8)
                                rx_shift <= {rx_shift[6:0], sda_i};
                        end
                    end
                    if (cnt_done) begin
                        cnt   <= 16'd0;
                        scl_o <= 1'b0;
                        if (bit_idx == 4'd8) begin
                            // 9 位完成
                            rsp_valid <= 1'b1;
                            rsp_data  <= rx_shift;
                            rsp_nack  <= nack_r;
                            state     <= ST_IDLE;
                        end else begin
                            bit_idx <= bit_idx + 4'd1;
                            // 预置下一位 SDA (SCL 低区变化)
                            if (op_r == OP_WRITE)
                                sda_o <= (bit_idx == 4'd7) ? 1'b1 : data_r[4'd6 - bit_idx];
                            else
                                sda_o <= (bit_idx == 4'd7) ? data_r[0] : 1'b1;  // READ 第9位: 0=ACK
                            state <= ST_LOW;
                        end
                    end else cnt <= cnt + 16'd1;
                end

                // ---- STOP ----
                ST_STOP_A: begin
                    if (cnt_done) begin
                        cnt   <= 16'd0;
                        scl_o <= 1'b1;
                        state <= ST_STOP_B;
                    end else cnt <= cnt + 16'd1;
                end
                ST_STOP_B: begin
                    if (scl_i) begin
                        cnt   <= 16'd0;
                        state <= ST_STOP_C;
                    end
                end
                ST_STOP_C: begin
                    if (cnt_done) begin
                        sda_o <= 1'b1;                  // SCL 高时 SDA 上升 = STOP
                        state <= ST_IDLE;
                    end else cnt <= cnt + 16'd1;
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

endmodule
