// matmul4x4: 4x4 int8 矩阵乘 -> int32 (参考实现, 套件自检用)
// 收 4 行 A/B (各 32bit), 末拍组合计算 16 个乘积累加, 再逐行吐出 C (128bit).
module matmul4x4 (
    input  wire         clk,
    input  wire         rst,
    input  wire         in_valid,
    output wire         in_ready,
    input  wire [31:0]  a_row,
    input  wire [31:0]  b_row,
    output reg          out_valid,
    input  wire         out_ready,
    output reg  [127:0] c_row
);
    localparam S_IN = 1'd0, S_OUT = 1'd1;
    reg st;
    reg [1:0] beat;   // 输入拍计数
    reg [1:0] orow;   // 输出拍计数

    reg signed [7:0]  A [0:3][0:3];
    reg signed [7:0]  B [0:3][0:3];
    reg signed [31:0] C [0:3][0:3];

    assign in_ready = (st == S_IN);

    wire push = in_valid && in_ready;
    wire pop  = out_valid && out_ready;

    integer i, j, k;
    reg signed [31:0] acc;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            st <= S_IN; beat <= 0; orow <= 0;
            out_valid <= 0;
        end else begin
            case (st)
                S_IN: begin
                    if (push) begin
                        for (j = 0; j < 4; j = j + 1) begin
                            A[beat][j] <= a_row[8*j +: 8];
                            B[beat][j] <= b_row[8*j +: 8];
                        end
                        if (beat == 2'd3) begin
                            // 末拍: 组合计算全部乘积 (含本拍数据)
                            for (i = 0; i < 4; i = i + 1) begin
                                for (j = 0; j < 4; j = j + 1) begin
                                    acc = 32'sd0;
                                    for (k = 0; k < 4; k = k + 1) begin
                                        // 本拍数据落在行/列索引 3, 其余用寄存器阵列
                                        acc = acc + $signed((i == 2'd3) ? a_row[8*k +: 8] : A[i][k])
                                                  * $signed((k == 2'd3) ? b_row[8*j +: 8] : B[k][j]);
                                    end
                                    C[i][j] <= acc;
                                end
                            end
                            st <= S_OUT;
                            beat <= 0;
                            orow <= 0;
                            out_valid <= 1;
                        end else begin
                            beat <= beat + 1;
                        end
                    end
                end
                S_OUT: begin
                    // c_row 组合呈现 (见 always_comb)
                    if (pop) begin
                        if (orow == 2'd3) begin
                            st <= S_IN;
                            out_valid <= 0;
                        end else begin
                            orow <= orow + 1;
                        end
                    end
                end
            endcase
        end
    end

    // 输出行组合拼接 (row i: C[i][0] 在 [31:0])
    integer r, c2;
    always_comb begin
        c_row = 128'd0;
        for (r = 0; r < 4; r = r + 1)
            for (c2 = 0; c2 < 4; c2 = c2 + 1)
                if (r == orow) c_row[32*c2 +: 32] = C[r][c2];
    end
endmodule
