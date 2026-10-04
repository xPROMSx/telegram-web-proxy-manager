/* Test-only candidate. Runs only inside the production isolation pipeline. */
#include <arpa/inet.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#ifndef ATTACK
#define ATTACK 0
#endif
int main(int argc, char **argv) {
#if ATTACK == 3
    /* A fake future candidate that always "accepts" TOML must fail the trusted
       unknown-key negative, despite a plausible stable --version. */
    if (argc == 3 && !strcmp(argv[1], "healthcheck")) return 0;
#endif
    if (argc != 2 || strcmp(argv[1], "--version")) return 99;
    if (getuid() == 0 || geteuid() == 0 || getenv("UPDATER_TEST_CANARY") ||
        getenv("HTTP_PROXY") || getenv("HTTPS_PROXY") || getenv("GITHUB_TOKEN")) return 98;
    FILE *status = fopen("/proc/self/status", "r");
    if (!status) return 97;
    char line[1024]; int capability = 0;
    while (fgets(line, sizeof(line), status)) {
        if (!strncmp(line, "CapEff:\t0000000000001000", 24)) capability = 1;
    }
    fclose(status);
    if (!capability) return 96;
    const char *targets[] = {"/root/update-host-canary", "/proc/1/root/root/update-host-canary",
        "/var/lib/telemt-web-manager/update-journal.json", "/root/telemt-backups/host-canary",
        "/var/lib/telemt/state/host-only-canary", "/etc/letsencrypt/archive/proxy.example.com/privkey1.pem",
        "/run/systemd/private", "/proc/1/root/run/systemd/private"};
    for (unsigned i = 0; i < sizeof(targets)/sizeof(targets[0]); i++) {
        int fd = open(targets[i], O_RDONLY);
        if (fd >= 0) { close(fd); return 95; }
        /* Writing the private DATA path is permitted; the host canary at the
           same absolute name is checked byte-for-byte by the trusted guest. */
        if (i == 4) continue;
        fd = open(targets[i], O_WRONLY | O_CREAT, 0600);
        if (fd >= 0) { close(fd); return 94; }
    }
    int fd = open("/etc/telemt/telemt.toml", O_WRONLY);
    if (fd >= 0) { close(fd); return 93; }
    int channel = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in host = {.sin_family=AF_INET, .sin_port=htons(443)};
    host.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if (channel < 0 || connect(channel,(struct sockaddr *)&host,sizeof(host)) == 0) return 92;
    close(channel);
    fd=open("/var/lib/telemt/state/isolation-child-ready",O_WRONLY|O_CREAT|O_EXCL,0600);
    if (fd < 0 || write(fd,"private child already exists",28)!=28 || fsync(fd)) return 91;
    close(fd);
#if ATTACK == 1
    if (fork() == 0) { setsid(); for (;;) pause(); }
    for (;;) pause();
#elif ATTACK == 2
    memset(line, 'x', sizeof(line));
    for (;;) if (write(STDOUT_FILENO,line,sizeof(line))<0) return 90;
#else
    puts("telemt 4.0.0");
    return 0;
#endif
}
