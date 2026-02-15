/* sys_yes.c — repeatedly output a string (default "y")
 *
 * Usage: yes [string]
 */
#include <stdio.h>

int main(int argc, char **argv) {
    const char *msg = "y";
    if (argc > 1)
        msg = argv[1];

    /* Buffer output for performance (like real yes) */
    char buf[8192];
    int len = 0;
    while (msg[len]) len++;

    int pos = 0;
    while (pos + len + 1 < (int)sizeof(buf)) {
        for (int i = 0; i < len; i++)
            buf[pos++] = msg[i];
        buf[pos++] = '\n';
    }

    for (;;) {
        if (fwrite(buf, 1, pos, stdout) == 0)
            break;
    }

    return 0;
}
