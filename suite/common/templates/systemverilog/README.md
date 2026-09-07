# SystemVerilog 工程约定

- 在 `impl/systemverilog/<case>/src/` 下放任意多个 `.sv`/`.v` 文件；
- 顶层模块名 = SPEC 顶层名（如 `sync_fifo`），端口与 SPEC 完全一致；
- 会被直接交给 Verilator 仿真（`-Wno-fatal`，警告不致命但请保持整洁），
  经 sv2v 转换后交给 Yosys 综合；
- 不需要 Makefile/脚本——harness 直接收集 `src/` 下全部源文件。
