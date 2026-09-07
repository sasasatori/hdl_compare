// uart_trx: 全双工 UART 8N1, LSB 先传.
// 1 tick = div clk; 1 bit = 16 tick. div 传输中稳定.
module uart_trx (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] div,
    input  wire [7:0]  tx_data,
    input  wire        tx_valid,
    output wire        tx_ready,
    output reg         txd,
    output wire        tx_busy,
    input  wire        rxd,
    output reg  [7:0]  rx_data,
    output reg         rx_valid,
    output reg         rx_err
);

    // ---------------- 发送器 ----------------
    localparam TX_IDLE = 1'b0, TX_RUN = 1'b1;
    reg        tx_state;
    reg [7:0]  tx_shift;    // 待发数据
    reg [3:0]  tx_bit;      // 0=起始位, 1..8=数据, 9=停止位
    reg [3:0]  tx_tick;     // 0..15
    reg [15:0] tx_cnt;      // 0..div-1

    assign tx_ready = (tx_state == TX_IDLE);
    assign tx_busy  = (tx_state == TX_RUN);

    wire tx_tick_end = (tx_cnt == div - 16'd1);

    always @(posedge clk) begin
        if (rst) begin
            tx_state <= TX_IDLE;
            tx_shift <= 8'd0;
            tx_bit   <= 4'd0;
            tx_tick  <= 4'd0;
            tx_cnt   <= 16'd0;
            txd      <= 1'b1;
        end else begin
            case (tx_state)
                TX_IDLE: begin
                    txd <= 1'b1;
                    if (tx_valid) begin
                        tx_state <= TX_RUN;
                        tx_shift <= tx_data;
                        tx_bit   <= 4'd0;
                        tx_tick  <= 4'd0;
                        tx_cnt   <= 16'd0;
                        txd      <= 1'b0;   // 起始位, 立即拉低
                    end
                end
                TX_RUN: begin
                    if (tx_tick_end) begin
                        tx_cnt <= 16'd0;
                        if (tx_tick == 4'd15) begin
                            tx_tick <= 4'd0;
                            if (tx_bit == 4'd9) begin
                                // 停止位结束, 回空闲
                                tx_state <= TX_IDLE;
                                txd      <= 1'b1;
                            end else begin
                                tx_bit <= tx_bit + 4'd1;
                                // 下一位电平
                                if (tx_bit == 4'd8)
                                    txd <= 1'b1;                    // 停止位
                                else
                                    txd <= tx_shift[tx_bit];        // D(bit)
                            end
                        end else begin
                            tx_tick <= tx_tick + 4'd1;
                        end
                    end else begin
                        tx_cnt <= tx_cnt + 16'd1;
                    end
                end
                default: tx_state <= TX_IDLE;
            endcase
        end
    end

    // ---------------- 接收器 ----------------
    localparam RX_IDLE = 2'd0, RX_START = 2'd1, RX_DATA = 2'd2, RX_STOP = 2'd3;
    reg [1:0]  rx_state;
    reg [3:0]  rx_bit;      // 数据位索引 0..7
    reg [3:0]  rx_tick;     // 0..15
    reg [15:0] rx_cnt;      // 0..div-1
    reg [7:0]  rx_shift;
    reg [1:0]  vote_cnt;    // 已采样次数 0..2
    reg [1:0]  vote_sum;    // 采样和 (0..3)

    // 输入同步 (2FF)
    reg rxd_s0, rxd_s1, rxd_s1_d;
    always @(posedge clk) begin
        if (rst) begin
            rxd_s0   <= 1'b1;
            rxd_s1   <= 1'b1;
            rxd_s1_d <= 1'b1;
        end else begin
            rxd_s0   <= rxd;
            rxd_s1   <= rxd_s0;
            rxd_s1_d <= rxd_s1;
        end
    end
    wire rx_fall = rxd_s1_d && !rxd_s1;

    wire rx_tick_end = (rx_cnt == div - 16'd1);

    always @(posedge clk) begin
        if (rst) begin
            rx_state <= RX_IDLE;
            rx_bit   <= 4'd0;
            rx_tick  <= 4'd0;
            rx_cnt   <= 16'd0;
            rx_shift <= 8'd0;
            vote_cnt <= 2'd0;
            vote_sum <= 2'd0;
            rx_data  <= 8'd0;
            rx_valid <= 1'b0;
            rx_err   <= 1'b0;
        end else begin
            rx_valid <= 1'b0;   // 默认单周期脉冲
            case (rx_state)
                RX_IDLE: begin
                    if (rx_fall) begin
                        rx_state <= RX_START;
                        rx_tick  <= 4'd0;
                        rx_cnt   <= 16'd0;
                    end
                end
                RX_START: begin
                    if (rx_tick_end) begin
                        rx_cnt <= 16'd0;
                        if (rx_tick == 4'd7) begin
                            // 半位处确认
                            if (rxd_s1 == 1'b0) begin
                                rx_tick <= rx_tick + 4'd1;  // 继续走完起始位
                            end else begin
                                rx_state <= RX_IDLE;  // 假起始
                            end
                        end else if (rx_tick == 4'd15) begin
                            // 起始位结束, 进入数据位 (位边界对齐)
                            rx_state <= RX_DATA;
                            rx_bit   <= 4'd0;
                            vote_cnt <= 2'd0;
                            vote_sum <= 2'd0;
                            rx_tick  <= 4'd0;
                        end else begin
                            rx_tick <= rx_tick + 4'd1;
                        end
                    end else begin
                        rx_cnt <= rx_cnt + 16'd1;
                    end
                end
                RX_DATA, RX_STOP: begin
                    if (rx_tick_end) begin
                        rx_cnt <= 16'd0;
                        // 进入 tick 7/8/9 的边界上采样 (位起始为 tick0)
                        if (rx_tick == 4'd6 || rx_tick == 4'd7 || rx_tick == 4'd8) begin
                            vote_sum <= vote_sum + {1'b0, rxd_s1};
                            vote_cnt <= vote_cnt + 2'd1;
                            if (vote_cnt == 2'd2) begin
                                // 第三次采样, 多数表决
                                if (rx_state == RX_DATA) begin
                                    rx_shift[rx_bit] <= (vote_sum + {1'b0, rxd_s1}) >= 2'd2;
                                end else begin
                                    // 停止位: 输出结果
                                    rx_data  <= rx_shift;
                                    rx_valid <= 1'b1;
                                    rx_err   <= !((vote_sum + {1'b0, rxd_s1}) >= 2'd2);
                                    rx_state <= RX_IDLE;
                                end
                                vote_cnt <= 2'd0;
                                vote_sum <= 2'd0;
                            end
                        end
                        if (rx_tick == 4'd15) begin
                            rx_tick <= 4'd0;
                            if (rx_state == RX_DATA) begin
                                if (rx_bit == 4'd7) begin
                                    rx_state <= RX_STOP;
                                    vote_cnt <= 2'd0;
                                    vote_sum <= 2'd0;
                                end else begin
                                    rx_bit <= rx_bit + 4'd1;
                                end
                            end
                        end else begin
                            rx_tick <= rx_tick + 4'd1;
                        end
                    end else begin
                        rx_cnt <= rx_cnt + 16'd1;
                    end
                end
                default: rx_state <= RX_IDLE;
            endcase
        end
    end

endmodule
