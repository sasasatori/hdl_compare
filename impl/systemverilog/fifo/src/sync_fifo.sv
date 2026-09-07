// sync_fifo: 16-deep x 8-bit synchronous FIFO, FWFT mode.
module sync_fifo (
    input  wire       clk,
    input  wire       rst,
    input  wire       in_valid,
    output wire       in_ready,
    input  wire [7:0] in_data,
    output wire       out_valid,
    input  wire       out_ready,
    output wire [7:0] out_data,
    output reg  [4:0] count,
    output wire       almost_full,
    output wire       almost_empty
);

    reg [7:0] mem [0:15];
    reg [3:0] wptr;
    reg [3:0] rptr;

    // 满时同拍推弹: 弹出即腾出空间, 当拍推入必须被接受
    assign in_ready  = (count != 5'd16) || (out_valid && out_ready);
    assign out_valid = (count != 5'd0);
    assign out_data  = mem[rptr];
    assign almost_full  = (count >= 5'd12);
    assign almost_empty = (count <= 5'd4);

    wire push = in_valid && in_ready;
    wire pop  = out_valid && out_ready;

    always @(posedge clk) begin
        if (rst) begin
            wptr  <= 4'd0;
            rptr  <= 4'd0;
            count <= 5'd0;
        end else begin
            if (push) begin
                mem[wptr] <= in_data;
                wptr <= wptr + 4'd1;
            end
            if (pop) begin
                rptr <= rptr + 4'd1;
            end
            case ({push, pop})
                2'b10:   count <= count + 5'd1;
                2'b01:   count <= count - 5'd1;
                default: count <= count;
            endcase
        end
    end

endmodule
