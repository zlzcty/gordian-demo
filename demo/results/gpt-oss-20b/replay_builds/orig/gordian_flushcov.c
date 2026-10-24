
/* gordian replay helper: flush llvm profile counters when the program crashes, aborts or runs
   past the per-test deadline (GORDIAN_REPLAY_TIMEOUT seconds), so coverage of crashing tests is kept. */
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>
int __llvm_profile_write_file(void);
static void gordian_flush_and_exit(int sig) { __llvm_profile_write_file(); _exit(128 + sig); }
__attribute__((constructor)) static void gordian_install(void) {
    int sigs[] = {SIGSEGV, SIGBUS, SIGFPE, SIGILL, SIGABRT, SIGALRM, SIGTERM, SIGINT};
    for (unsigned i = 0; i < sizeof sigs / sizeof *sigs; i++) {
        struct sigaction sa; sa.sa_handler = gordian_flush_and_exit; sigemptyset(&sa.sa_mask); sa.sa_flags = SA_RESETHAND;
        sigaction(sigs[i], &sa, 0);
    }
    const char *t = getenv("GORDIAN_REPLAY_TIMEOUT");
    if (t && atoi(t) > 0) alarm((unsigned)atoi(t));
}
