// uart_trx: 8N1 UART 收发器 (参考实现, 套件自检用)
// 位时间 = 16*div clk; RX 16x 过采样, 位中点 7/8/9 tick 三次采样多数表决.
module uart_trx (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] div,
    input  wire [7:0]  tx_data,
    input  wire        tx_valid,
    output reg         tx_ready,
    output reg         txd,
    output reg         tx_busy,
    input  wire        rxd,
    output reg  [7:0]  rx_data,
    output reg         rx_valid,
    output reg         rx_err
);
    // ---------------- TX ----------------
    localparam TX_IDLE = 2'd0, TX_START = 2'd1, TX_DATA = 2'd2, TX_STOP = 2'd3;
    reg [1:0]  tx_st;
    reg [15:0] tx_dcnt;
    reg [3:0]  tx_tick;
    reg [2:0]  tx_bit;
    reg [7:0]  tx_shift;
    wire       tx_tp = (tx_dcnt == div - 16'd1);  // tick 脉冲

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            tx_st <= TX_IDLE; tx_dcnt <= 0; tx_tick <= 0; tx_bit <= 0;
            tx_shift <= 0; txd <= 1'b1; tx_busy <= 0; tx_ready <= 1;
        end else begin
            case (tx_st)
                TX_IDLE: begin
                    txd <= 1'b1; tx_busy <= 0; tx_ready <= 1;
                    if (tx_valid && tx_ready) begin
                        tx_shift <= tx_data;
                        tx_st    <= TX_START;
                        tx_dcnt  <= 0;
                        tx_tick  <= 0;
                        tx_busy  <= 1;
                        tx_ready <= 0;
                        txd      <= 1'b0;  // 起始位立即开始
                    end
                end
                TX_START: begin
                    txd <= 1'b0;
                    if (tx_tp) begin
                        tx_dcnt <= 0;
                        if (tx_tick == 4'd15) begin
                            tx_tick <= 0;
                            tx_st   <= TX_DATA;
                            tx_bit  <= 0;
                            txd     <= tx_shift[0];
                        end else begin
                            tx_tick <= tx_tick + 1;
                        end
                    end else begin
                        tx_dcnt <= tx_dcnt + 1;
                    end
                end
                TX_DATA: begin
                    if (tx_tp) begin
                        tx_dcnt <= 0;
                        if (tx_tick == 4'd15) begin
                            tx_tick <= 0;
                            if (tx_bit == 3'd7) begin
                                tx_st <= TX_STOP;
                                txd   <= 1'b1;
                            end else begin
                                tx_bit <= tx_bit + 1;
                                txd    <= tx_shift[tx_bit + 1];
                            end
                        end else begin
                            tx_tick <= tx_tick + 1;
                        end
                    end else begin
                        tx_dcnt <= tx_dcnt + 1;
                    end
                end
                TX_STOP: begin
                    txd <= 1'b1;
                    if (tx_tp) begin
                        tx_dcnt <= 0;
                        if (tx_tick == 4'd15) begin
                            tx_st    <= TX_IDLE;
                            tx_busy  <= 0;
                            tx_ready <= 1;
                        end else begin
                            tx_tick <= tx_tick + 1;
                        end
                    end else begin
                        tx_dcnt <= tx_dcnt + 1;
                    end
                end
            endcase
        end
    end

    // ---------------- RX ----------------
    // 采样窗: 起始位确认于 tick8 (起始位中点), 之后每 bit 16 tick 窗,
    // 在窗尾 tick15 与下一窗 tick0/tick1 三次采样做多数表决 (位中点 ±1 tick).
    localparam RX_IDLE = 2'd0, RX_START = 2'd1, RX_DATA = 2'd2, RX_STOP = 2'd3;
    reg [1:0]  rx_st;
    reg [15:0] rx_dcnt;
    reg [3:0]  rx_tick;
    reg [2:0]  rx_bit;
    reg [7:0]  rx_shift;
    reg [1:0]  rx_samp;   // 前两次采样
    reg        rx_armed;  // 首个 tick15 之后才允许在 tick1 表决 (避开起始位窗口)
    reg        rxd_d;
    wire       rx_tp = (rx_dcnt == div - 16'd1);
    wire       rx_maj = (rx_samp[0] & rx_samp[1]) | (rx_samp[1] & rxd) | (rx_samp[0] & rxd);

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            rx_st <= RX_IDLE; rx_dcnt <= 0; rx_tick <= 0; rx_bit <= 0;
            rx_shift <= 0; rx_samp <= 0; rx_armed <= 0; rxd_d <= 1;
            rx_data <= 0; rx_valid <= 0; rx_err <= 0;
        end else begin
            rxd_d <= rxd;
            rx_valid <= 0;  // 单拍脉冲默认
            rx_err   <= 0;
            case (rx_st)
                RX_IDLE: begin
                    if (rxd_d == 1 && rxd == 0) begin  // 下降沿: 候选起始位
                        rx_st   <= RX_START;
                        rx_dcnt <= 0;
                        rx_tick <= 0;
                    end
                end
                RX_START: begin
                    if (rx_tp) begin
                        rx_dcnt <= 0;
                        if (rx_tick == 4'd8) begin  // 起始位中点确认
                            rx_tick <= 0;
                            if (rxd == 0) begin
                                rx_st   <= RX_DATA;
                                rx_bit  <= 0;
                                rx_samp <= 0;
                                rx_armed <= 0;
                            end else begin
                                rx_st <= RX_IDLE;  // 假起始
                            end
                        end else begin
                            rx_tick <= rx_tick + 1;
                        end
                    end else begin
                        rx_dcnt <= rx_dcnt + 1;
                    end
                end
                RX_DATA, RX_STOP: begin
                    if (rx_tp) begin
                        rx_dcnt <= 0;
                        if (rx_tick == 4'd15) begin
                            rx_samp[0] <= rxd;
                            rx_armed   <= 1;
                        end else if (rx_tick == 4'd0) begin
                            rx_samp[1] <= rxd;
                        end else if (rx_tick == 4'd1 && rx_armed) begin
                            // 窗中点: 表决落锤
                            if (rx_st == RX_DATA) begin
                                rx_shift[rx_bit] <= rx_maj;
                                if (rx_bit == 3'd7) begin
                                    rx_st <= RX_STOP;
                                end else begin
                                    rx_bit <= rx_bit + 1;
                                end
                            end else begin  // RX_STOP: 停止位应为 1
                                rx_st    <= RX_IDLE;
                                rx_valid <= 1;
                                rx_err   <= ~rx_maj;
                                rx_data  <= rx_shift;
                            end
                        end
                        rx_tick <= (rx_tick == 4'd15) ? 4'd0 : rx_tick + 1;
                    end else begin
                        rx_dcnt <= rx_dcnt + 1;
                    end
                end
            endcase
        end
    end
endmodule
