`default_nettype wire
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
    output wire [7:0]  rx_data,
    output wire        rx_valid,
    output wire        rx_err
);
    wire [12:0] o;
    \uart::uart_trx_impl u_impl (
        .clk_i     (clk),
        .rst_i     (rst),
        .div_i     (div),
        .tx_data_i (tx_data),
        .tx_valid_i(tx_valid),
        .rxd_i     (rxd),
        .output__  (o)
    );
    assign tx_ready = o[12];
    assign txd      = o[11];
    assign tx_busy  = o[10];
    assign rx_data  = o[9:2];
    assign rx_valid = o[1];
    assign rx_err   = o[0];
endmodule
