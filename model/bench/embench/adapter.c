/* Bridges Embench's benchmark API to the PARISCV harness.
   Only initialise_benchmark()/benchmark() are timed-relevant; the harness calls
   benchmark_init() before starting the cycle counter and benchmark_run()
   inside the measured window. */
extern void initialise_benchmark(void);
extern int  benchmark(void);
extern int  verify_benchmark(int result);

void benchmark_init(void) { initialise_benchmark(); }
int  benchmark_run(void)  { return benchmark(); }

/* Embench support hooks that the bare-metal build does not need. */
void initialise_board(void) { }
void start_trigger(void) { }
void stop_trigger(void) { }

/* Some Embench kernels (e.g. crc32) have no initialise_benchmark(); supply a
   weak no-op so a single adapter covers every kernel. */
__attribute__((weak)) void initialise_benchmark(void) { }
