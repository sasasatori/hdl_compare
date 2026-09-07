// uart_trx (sv_v2): 8N1 UART, 基于 SVP 原语: 收发帧 = svp_shift (零逻辑移位),
// 位时基 = svp_tick_gen; RX 16x 过采样 + 位中点 7/8/9 tick 三采样多数表决.
module uart_trx (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] div,
    input  wire [7:0]  tx_data,
    input  wire        tx_valid,
    output wire        tx_ready,
    output wire        txd,
    output wire        tx_busy,
    input  wire        rxd,
    output reg  [7:0]  rx_data,
    output reg         rx_valid,
    output reg         rx_err
);
    // ---------------- TX ----------------
    reg       tx_run;
    reg [3:0] tx_tick;   // 0..15
    reg [3:0] tx_bits;   // 0..9 (10 位移出完毕)
    wire      tx_sout;
    wire      tx_tp;
    wire tx_load = tx_valid && tx_ready;
    svp_shift #(.W(10), .FILL(1'b1)) u_tx_frame (
        .clk(clk), .rst(rst),
        .en(tx_tp && (tx_tick == 4'd15) && tx_run),
        .load(tx_load),
        .pdata({1'b1, tx_data, 1'b0}),  // bit0=start(0), bit9=stop(1)
        .sin(1'b1),
        .q(),
        .sout(tx_sout)
    );

    svp_tick_gen #(.W(16)) u_tx_tick (
        .clk(clk), .rst(rst), .en(tx_run), .div(div), .tick(tx_tp), .cnt()
    );

    assign txd      = tx_run ? tx_sout : 1'b1;
    assign tx_ready = ~tx_run;
    assign tx_busy  = tx_run;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            tx_run <= 0; tx_tick <= 0; tx_bits <= 0;
        end else if (!tx_run) begin
            if (tx_load) begin
                tx_run  <= 1;
                tx_tick <= 0;
                tx_bits <= 0;
            end
        end else begin
            if (tx_tp) begin
                if (tx_tick == 4'd15) begin
                    tx_tick <= 0;
                    if (tx_bits == 4'd9) tx_run <= 0;      // 第 10 位移出完成
                    else                 tx_bits <= tx_bits + 1;
                end else begin
                    tx_tick <= tx_tick + 1;
                end
            end
        end
    end

    // ---------------- RX ----------------
    localparam RX_IDLE = 2'd0, RX_START = 2'd1, RX_DATA = 2'd2;
    reg [1:0]  rx_st;
    reg [3:0]  rx_tick;
    reg [3:0]  rx_bits;
    reg [1:0]  rx_samp;
    reg        rx_armed;
    wire       rx_tp;
    wire [15:0] rx_dcnt;
    reg        rxd_d;
    wire       rx_maj = (rx_samp[0] & rx_samp[1]) | (rx_samp[1] & rxd) | (rx_samp[0] & rxd);

    wire rx_en = rx_tp && (rx_tick == 4'd1) && rx_armed && (rx_st == RX_DATA);
    wire [9:0] rx_q;
    svp_shift #(.W(10), .FILL(1'b0)) u_rx_frame (
        .clk(clk), .rst(rst), .en(rx_en), .load(1'b0), .pdata(10'd0),
        .sin(rx_maj), .q(rx_q), .sout()
    );
    wire [9:0] rx_frame_next = {rx_maj, rx_q[9:1]};

    svp_tick_gen #(.W(16)) u_rx_tick (
        .clk(clk), .rst(rst), .en(rx_st != RX_IDLE), .div(div), .tick(rx_tp), .cnt(rx_dcnt)
    );

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            rx_st <= RX_IDLE; rx_tick <= 0; rx_bits <= 0;
            rx_samp <= 0; rx_armed <= 0; rxd_d <= 1;
            rx_data <= 0; rx_valid <= 0; rx_err <= 0;
        end else begin
            rxd_d <= rxd;
            rx_valid <= 0;
            rx_err   <= 0;
            case (rx_st)
                RX_IDLE: begin
                    if (rxd_d == 1 && rxd == 0) begin
                        rx_st   <= RX_START;
                        rx_tick <= 0;
                    end
                end
                RX_START: begin
                    if (rx_tp) begin
                        if (rx_tick == 4'd8) begin  // 起始位中点确认
                            rx_tick <= 0;
                            if (rxd == 0) begin
                                rx_st    <= RX_DATA;
                                rx_bits  <= 0;
                                rx_samp  <= 0;
                                rx_armed <= 0;
                            end else begin
                                rx_st <= RX_IDLE;  // 假起始
                            end
                        end else begin
                            rx_tick <= rx_tick + 1;
                        end
                    end
                end
                RX_DATA: begin
                    if (rx_tp) begin
                        if (rx_tick == 4'd15) begin
                            rx_samp[0] <= rxd;
                            rx_armed   <= 1;
                        end else if (rx_tick == 4'd0) begin
                            rx_samp[1] <= rxd;
                        end else if (rx_tick == 4'd1 && rx_armed) begin
                            if (rx_bits == 4'd8) begin
                                // 第 9 次表决 = 停止位; 帧内为 {stop,d7..d0,x}
                                rx_st    <= RX_IDLE;
                                rx_valid <= 1;
                                rx_err   <= ~rx_maj;
                                rx_data  <= rx_frame_next[8:1];
                            end else begin
                                rx_bits <= rx_bits + 1;
                            end
                        end
                        rx_tick <= (rx_tick == 4'd15) ? 4'd0 : rx_tick + 1;
                    end
                end
                default: rx_st <= RX_IDLE;
            endcase
        end
    end
endmodule
