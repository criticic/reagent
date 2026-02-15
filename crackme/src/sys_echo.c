/* sys_echo.c — write arguments to stdout
 *
 * Supports -n (no trailing newline) and -e (interpret escapes).
 * Based on POSIX / BSD echo behaviour.
 */
#include <stdio.h>
#include <string.h>

static void put_escaped(const char *s) {
    for (; *s; s++) {
        if (*s == '\\' && *(s + 1)) {
            s++;
            switch (*s) {
            case 'n':  putchar('\n'); break;
            case 't':  putchar('\t'); break;
            case 'r':  putchar('\r'); break;
            case '\\': putchar('\\'); break;
            case 'a':  putchar('\a'); break;
            case 'b':  putchar('\b'); break;
            case 'f':  putchar('\f'); break;
            case 'v':  putchar('\v'); break;
            case '0': {
                unsigned val = 0;
                for (int i = 0; i < 3 && s[1] >= '0' && s[1] <= '7'; i++)
                    val = val * 8 + (*++s - '0');
                putchar(val);
                break;
            }
            default:
                putchar('\\');
                putchar(*s);
                break;
            }
        } else {
            putchar(*s);
        }
    }
}

int main(int argc, char **argv) {
    int trailing_newline = 1;
    int interpret_escapes = 0;
    int i = 1;

    /* Parse flags */
    while (i < argc) {
        if (argv[i][0] != '-') break;
        int all_flags = 1;
        for (const char *p = argv[i] + 1; *p; p++) {
            if (*p == 'n')      trailing_newline = 0;
            else if (*p == 'e') interpret_escapes = 1;
            else if (*p == 'E') interpret_escapes = 0;
            else { all_flags = 0; break; }
        }
        if (!all_flags) break;
        i++;
    }

    for (; i < argc; i++) {
        if (i > 1 && !(i == 1)) /* always true after first arg printed */
            ; /* space already handled below */
        if (interpret_escapes)
            put_escaped(argv[i]);
        else
            fputs(argv[i], stdout);
        if (i + 1 < argc)
            putchar(' ');
    }

    if (trailing_newline)
        putchar('\n');

    return 0;
}
