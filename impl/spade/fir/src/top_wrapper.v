`default_nettype wire
module fir16 (
    input  wire        clk,
    input  wire        rst,
    input  wire        coef_we,
    input  wire [3:0]  coef_addr,
    input  wire [15:0] coef_data,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [15:0] in_data,
    output wire        out_valid,
    input  wire        out_ready,
    output wire [15:0] out_data
);
    wire [17:0] o;
    \fir::fir16_impl u_impl (
        .clk_i      (clk),
        .rst_i      (rst),
        .coef_we_i  (coef_we),
        .coef_addr_i(coef_addr),
        .coef_data_i(coef_data),
        .in_valid_i (in_valid),
        .in_data_i  (in_data),
        .out_ready_i(out_ready),
        .output__   (o)
    );
    assign in_ready  = o[17];
    assign out_valid = o[16];
    assign out_data  = o[15:0];
endmodule
