`default_nettype wire
module i2c_master (
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] div,
    input  wire        cmd_valid,
    output wire        cmd_ready,
    input  wire [1:0]  cmd_op,
    input  wire [7:0]  cmd_data,
    output wire        rsp_valid,
    output wire [7:0]  rsp_data,
    output wire        rsp_nack,
    output wire        busy,
    output wire        scl_o,
    input  wire        scl_i,
    output wire        sda_o,
    input  wire        sda_i
);
    wire [13:0] o;
    \i2c_master::i2c_master_impl u_impl (
        .clk_i      (clk),
        .rst_i      (rst),
        .div_i      (div),
        .cmd_valid_i(cmd_valid),
        .cmd_op_i   (cmd_op),
        .cmd_data_i (cmd_data),
        .scl_i_i    (scl_i),
        .sda_i_i    (sda_i),
        .output__   (o)
    );
    assign cmd_ready = o[13];
    assign rsp_valid = o[12];
    assign rsp_data  = o[11:4];
    assign rsp_nack  = o[3];
    assign busy      = o[2];
    assign scl_o     = o[1];
    assign sda_o     = o[0];
endmodule
