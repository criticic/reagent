/* sys_cat.c — concatenate files to stdout
 *
 * Usage: cat [file ...]
 * Reads stdin if no files given or if "-" is specified.
 */
#include <stdio.h>
#include <string.h>

static int cat_fd(FILE *fp) {
    char buf[8192];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), fp)) > 0) {
        if (fwrite(buf, 1, n, stdout) != n)
            return 1;
    }
    return ferror(fp) ? 1 : 0;
}

int main(int argc, char **argv) {
    int rc = 0;

    if (argc < 2) {
        rc = cat_fd(stdin);
    } else {
        for (int i = 1; i < argc; i++) {
            if (strcmp(argv[i], "-") == 0) {
                rc |= cat_fd(stdin);
            } else {
                FILE *fp = fopen(argv[i], "rb");
                if (!fp) {
                    fprintf(stderr, "cat: %s: No such file or directory\n", argv[i]);
                    rc = 1;
                    continue;
                }
                rc |= cat_fd(fp);
                fclose(fp);
            }
        }
    }

    return rc;
}
