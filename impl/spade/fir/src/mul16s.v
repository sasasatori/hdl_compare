`default_nettype wire
// 16x16 有符号乘法器: 操作数声明为 signed, 使 yosys 前端直接生成窄 $mul
// (Spade 生成的 $signed(x)*$signed(c) 会被 Verilog 上下文扩展规则放大为 32x32).
module \fir::mul16s (
    input  wire [15:0] a_i,
    input  wire [15:0] b_i,
    output wire [31:0] output__
);
    wire signed [15:0] sa = a_i;
    wire signed [15:0] sb = b_i;
    wire signed [31:0] sy = sa * sb;
    assign output__ = sy;
endmodule
