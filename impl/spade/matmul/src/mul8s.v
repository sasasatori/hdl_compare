`default_nettype wire
// 8x8 有符号乘法器: 操作数声明为 signed, 使 yosys 前端直接生成窄 $mul.
module \matmul::mul8s (
    input  wire [7:0] a_i,
    input  wire [7:0] b_i,
    output wire [15:0] output__
);
    wire signed [7:0] sa = a_i;
    wire signed [7:0] sb = b_i;
    wire signed [15:0] sy = sa * sb;
    assign output__ = sy;
endmodule
