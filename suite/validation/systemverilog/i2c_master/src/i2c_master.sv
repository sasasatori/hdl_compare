// i2c_master: 字节级 I2C 主控制器 (参考实现, 套件自检用)
// 半周期 = div clk; 开漏建模: _o=0 拉低, _o=1 释放; 时钟延展: 释放 SCL 后等 scl_i==1.
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

    localparam ST_IDLE   = 4'd0,
               ST_START1 = 4'd1,   // 总线高位期 (重复START时先释放scl等高), 然后 sda 拉低
               ST_START2 = 4'd2,   // scl 拉低
               ST_PAUSE  = 4'd3,   // 字节间: scl 低, sda 释放
               ST_BIT_LO = 4'd4,   // scl 低半周 (数据建立)
               ST_BIT_HI = 4'd5,   // scl 高半周 (含延展等待)
               ST_ACK_LO = 4'd6,
               ST_ACK_HI = 4'd7,
               ST_STOP1  = 4'd8,   // sda 拉低 (scl 低)
               ST_STOP2  = 4'd9,   // 释放 scl, 等高
               ST_STOP3  = 4'd10;  // 释放 sda: STOP 条件

    reg [3:0]  st;
    reg [15:0] hcnt;      // 半周期计数
    reg [2:0]  bit_idx;
    reg [7:0]  tx_shift;
    reg [7:0]  rx_shift;
    reg        reading;   // 当前字节为读
    reg        ack_drive; // 读模式第 9 位: 0=驱动低(ACK), 1=释放(NACK)
    reg        nack_r;

    assign cmd_ready = (st == ST_IDLE) || (st == ST_PAUSE);
    assign busy      = (st != ST_IDLE);
    wire half = (hcnt == {1'b0, div[15:1]});  // div/2 点 (div>=4)
    wire phase_done = (hcnt == div - 16'd1);

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            st <= ST_IDLE;
            scl_o <= 1; sda_o <= 1;
            hcnt <= 0; bit_idx <= 0;
            tx_shift <= 0; rx_shift <= 0; reading <= 0; ack_drive <= 0;
            rsp_valid <= 0; rsp_data <= 0; rsp_nack <= 0; nack_r <= 0;
        end else begin
            rsp_valid <= 0;  // 脉冲默认
            case (st)
                ST_IDLE, ST_PAUSE: begin
                    if (st == ST_IDLE) begin
                        scl_o <= 1; sda_o <= 1;
                    end else begin
                        scl_o <= 0; sda_o <= 1;
                    end
                    hcnt <= 0;
                    if (cmd_valid && cmd_ready) begin
                        case (cmd_op)
                            OP_START: begin
                                st <= ST_START1;
                                if (st == ST_IDLE) begin
                                    sda_o <= 0;  // scl 高: 首 START 条件
                                end else begin
                                    scl_o <= 1; sda_o <= 1;  // 重复 START: 先释放总线
                                end
                            end
                            OP_WRITE: begin
                                tx_shift <= cmd_data;
                                reading  <= 0;
                                bit_idx  <= 0;
                                sda_o    <= cmd_data[7];  // 首位在 scl 低期间建立
                                st       <= ST_BIT_LO;
                            end
                            OP_READ: begin
                                reading   <= 1;
                                ack_drive <= cmd_data[0];
                                bit_idx   <= 0;
                                sda_o     <= 1;  // 释放
                                st        <= ST_BIT_LO;
                            end
                            OP_STOP: begin
                                sda_o <= 0;  // scl 低期间拉低 sda
                                st    <= ST_STOP1;
                            end
                        endcase
                    end
                end

                ST_START1: begin
                    if (scl_i == 1) begin
                        if (phase_done) begin
                            hcnt  <= 0;
                            sda_o <= 0;  // sda 1->0 @ scl 高 = START
                            st    <= ST_START2;
                        end else begin
                            hcnt <= hcnt + 1;
                        end
                    end
                end
                ST_START2: begin
                    if (half) begin
                        hcnt  <= 0;
                        scl_o <= 0;
                        st    <= ST_PAUSE;
                    end else begin
                        hcnt <= hcnt + 1;
                    end
                end

                ST_BIT_LO: begin
                    if (phase_done) begin
                        hcnt  <= 0;
                        scl_o <= 1;
                        st    <= ST_BIT_HI;
                    end else begin
                        hcnt <= hcnt + 1;
                    end
                end
                ST_BIT_HI: begin
                    if (scl_i == 1) begin  // 延展等待结束
                        if (reading && half)
                            rx_shift <= {rx_shift[6:0], sda_i};
                        if (phase_done) begin
                            hcnt  <= 0;
                            scl_o <= 0;
                            if (bit_idx == 3'd7) begin
                                st    <= ST_ACK_LO;
                                sda_o <= reading ? ack_drive : 1'b1;  // 写: 释放等从机 ACK
                            end else begin
                                bit_idx <= bit_idx + 1;
                                st      <= ST_BIT_LO;
                                if (!reading) begin
                                    tx_shift <= {tx_shift[6:0], 1'b0};
                                    sda_o    <= tx_shift[6];  // 下一位
                                end else begin
                                    sda_o <= 1'b1;
                                end
                            end
                        end else begin
                            hcnt <= hcnt + 1;
                        end
                    end
                end
                ST_ACK_LO: begin
                    if (phase_done) begin
                        hcnt  <= 0;
                        scl_o <= 1;
                        st    <= ST_ACK_HI;
                    end else begin
                        hcnt <= hcnt + 1;
                    end
                end
                ST_ACK_HI: begin
                    if (scl_i == 1) begin
                        if (!reading && half)
                            nack_r <= sda_i;  // 0=ACK, 1=NACK
                        if (phase_done) begin
                            hcnt      <= 0;
                            scl_o     <= 0;
                            sda_o     <= 1;
                            st        <= ST_PAUSE;
                            rsp_valid <= 1;
                            rsp_data  <= rx_shift;
                            rsp_nack  <= reading ? 1'b0 : nack_r;
                        end else begin
                            hcnt <= hcnt + 1;
                        end
                    end
                end

                ST_STOP1: begin
                    if (phase_done) begin
                        hcnt  <= 0;
                        scl_o <= 1;
                        st    <= ST_STOP2;
                    end else begin
                        hcnt <= hcnt + 1;
                    end
                end
                ST_STOP2: begin
                    if (scl_i == 1) begin
                        if (phase_done) begin
                            hcnt  <= 0;
                            sda_o <= 1;  // sda 0->1 @ scl 高 = STOP
                            st    <= ST_STOP3;
                        end else begin
                            hcnt <= hcnt + 1;
                        end
                    end
                end
                ST_STOP3: begin
                    if (half) begin
                        hcnt <= 0;
                        st   <= ST_IDLE;
                    end else begin
                        hcnt <= hcnt + 1;
                    end
                end
                default: st <= ST_IDLE;
            endcase
        end
    end
endmodule
