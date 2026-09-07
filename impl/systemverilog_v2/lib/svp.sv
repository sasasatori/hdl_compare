// ============================================================================
// svp.sv — SystemVerilog Primitives (SVP) v1
// 经 hdl_compare 评估验证的"好结构"原语库. 使用规约见 impl/systemverilog_v2/README.md
// 设计原则: 每个原语把一个已被证明优于"徒手惯写法"的结构固化为可复用模块;
// 全部同步/异步高有效复位兼容 (本库内部用异步, 契约只要求沿后语义).
// ============================================================================

// ---------------------------------------------------------------------------
// svp_shift: 参数化右移寄存器 (LSB 先出)
// 替代: 动态索引写 (rx_shift[idx]<=x 会产生每位使能 mux+解码器, uart 实测 -22% 面积)
// 用途: 串并转换/帧移位/Serializer/CRC/LFSR. 装载优先于移位.
// ---------------------------------------------------------------------------
module svp_shift #(
    parameter W    = 8,
    parameter FILL = 1'b1   // 复位值/默认移入位 (uart 空闲为 1)
) (
    input  wire         clk,
    input  wire         rst,
    input  wire         en,     // 移位使能: 1 拍右移 1 位
    input  wire         load,   // 同步并行装载 (优先)
    input  wire [W-1:0] pdata,  // 装载值 (bit0 最先移出)
    input  wire         sin,    // 移入位 (进入 MSB)
    output wire [W-1:0] q,
    output wire         sout    // = q[0]
);
    reg [W-1:0] r;
    assign q    = r;
    assign sout = r[0];
    always_ff @(posedge clk or posedge rst) begin
        if (rst)       r <= {W{FILL}};
        else if (load) r <= pdata;
        else if (en)   r <= {sin, r[W-1:1]};
    end
endmodule

// ---------------------------------------------------------------------------
// svp_add_tree: N 个有符号数的平衡加法树 (递归 generate)
// 替代: for 循环 acc = acc + x[i] (16 级线性进位链, fir 实测关键路径 21ns vs 16.6ns)
// in_flat: N 个数拼接, 低 W 位为第 0 个; out: 宽 W+clog2(N), 无溢出.
// ---------------------------------------------------------------------------
module svp_add_tree #(
    parameter N = 2,
    parameter W = 32
) (
    input  wire signed [N*W-1:0]       in_flat,
    output wire signed [W+$clog2(N)-1:0] out
);
    generate
        if (N == 1) begin : g_leaf
            assign out = in_flat[W-1:0];
        end else begin : g_node
            localparam NL = N / 2;
            localparam NR = N - NL;
            wire signed [W+$clog2(NL)-1:0] l;
            wire signed [W+$clog2(NR)-1:0] r;
            svp_add_tree #(NL, W) gl (.in_flat(in_flat[NL*W-1:0]),   .out(l));
            svp_add_tree #(NR, W) gr (.in_flat(in_flat[N*W-1:NL*W]), .out(r));
            assign out = l + r;
        end
    endgenerate
endmodule

// ---------------------------------------------------------------------------
// svp_tick_gen: 可编程分频 tick 产生器 (uart/i2c 位时基/波特率)
// tick = 组合脉冲 (cnt==div-1), 该拍末 cnt 归零; en=0 时 cnt 清零 (相位复位).
// cnt 输出供需要中点采样的场景 (如 i2c 在 div/2 处采样).
// ---------------------------------------------------------------------------
module svp_tick_gen #(
    parameter W = 16
) (
    input  wire         clk,
    input  wire         rst,
    input  wire         en,
    input  wire [W-1:0] div,
    output wire         tick,
    output reg  [W-1:0] cnt
);
    assign tick = en && (cnt == div - 1'b1);
    always_ff @(posedge clk or posedge rst) begin
        if (rst)      cnt <= {W{1'b0}};
        else if (!en) cnt <= {W{1'b0}};
        else if (tick) cnt <= {W{1'b0}};
        else           cnt <= cnt + 1'b1;
    end
endmodule

// ---------------------------------------------------------------------------
// svp_rnd_sat: 定点 round-half-up + 算术右移 + 饱和收窄
// 替代: 徒手舍入/饱和 (fir 位精确语义的标准件: y = sat((x + 2^(FRAC-1)) >>> FRAC))
// ---------------------------------------------------------------------------
module svp_rnd_sat #(
    parameter IW   = 36,  // 输入位宽 (signed)
    parameter OW   = 16,  // 输出位宽 (signed)
    parameter FRAC = 15   // 小数位 (右移位数, >=1)
) (
    input  wire signed [IW-1:0] in,
    output wire signed [OW-1:0] out
);
    wire signed [IW-1:0] in_r = in + {{(IW-FRAC){1'b0}}, 1'b1, {(FRAC-1){1'b0}}};
    wire signed [IW-1:0] sh   = in_r >>> FRAC;
    localparam signed [OW-1:0] VMAX = {1'b0, {(OW-1){1'b1}}};
    localparam signed [OW-1:0] VMIN = {1'b1, {(OW-1){1'b0}}};
    wire signed [IW-1:0] vmax_x = {{(IW-OW){VMAX[OW-1]}}, VMAX};
    wire signed [IW-1:0] vmin_x = {{(IW-OW){VMIN[OW-1]}}, VMIN};
    assign out = (sh > vmax_x) ? VMAX : (sh < vmin_x) ? VMIN : sh[OW-1:0];
endmodule

// ---------------------------------------------------------------------------
// svp_fifo: FWFT 同步 FIFO (评估验证结构: 满且同拍弹出时仍可写)
// 通用件: 任何 ready/valid 解耦场景直接用, 不要徒手再写指针 (边界易错).
// ---------------------------------------------------------------------------
module svp_fifo #(
    parameter DEPTH = 16,
    parameter W     = 8,
    parameter AF_TH = 12,
    parameter AE_TH = 4,
    parameter CW    = $clog2(DEPTH+1)
) (
    input  wire           clk,
    input  wire           rst,
    input  wire           in_valid,
    output wire           in_ready,
    input  wire [W-1:0]   in_data,
    output wire           out_valid,
    input  wire           out_ready,
    output wire [W-1:0]   out_data,
    output reg  [CW-1:0]  count,
    output wire           almost_full,
    output wire           almost_empty
);
    localparam PW = $clog2(DEPTH);
    reg [W-1:0] mem [0:DEPTH-1];
    reg [PW-1:0] wr_ptr, rd_ptr;

    wire full  = (count == DEPTH[CW-1:0]);
    wire empty = (count == {CW{1'b0}});
    wire pop   = out_valid && out_ready;

    assign in_ready     = !full || pop;
    assign out_valid    = !empty;
    assign out_data     = mem[rd_ptr];
    assign almost_full  = (count >= AF_TH[CW-1:0]);
    assign almost_empty = (count <= AE_TH[CW-1:0]);

    wire push = in_valid && in_ready;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            wr_ptr <= {PW{1'b0}};
            rd_ptr <= {PW{1'b0}};
            count  <= {CW{1'b0}};
        end else begin
            if (push) begin
                mem[wr_ptr] <= in_data;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (pop) begin
                rd_ptr <= rd_ptr + 1'b1;
            end
            case ({push, pop})
                2'b10:   count <= count + 1'b1;
                2'b01:   count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule
