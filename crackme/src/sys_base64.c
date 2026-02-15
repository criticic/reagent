/* sys_base64.c — base64 encode/decode
 *
 * Usage: base64 [-d] [file]
 * Encodes stdin (or file) to base64, or decodes with -d.
 */
#include <stdio.h>
#include <string.h>

static const char b64enc[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static const unsigned char b64dec[256] = {
    ['A'] = 0,  ['B'] = 1,  ['C'] = 2,  ['D'] = 3,  ['E'] = 4,  ['F'] = 5,
    ['G'] = 6,  ['H'] = 7,  ['I'] = 8,  ['J'] = 9,  ['K'] = 10, ['L'] = 11,
    ['M'] = 12, ['N'] = 13, ['O'] = 14, ['P'] = 15, ['Q'] = 16, ['R'] = 17,
    ['S'] = 18, ['T'] = 19, ['U'] = 20, ['V'] = 21, ['W'] = 22, ['X'] = 23,
    ['Y'] = 24, ['Z'] = 25,
    ['a'] = 26, ['b'] = 27, ['c'] = 28, ['d'] = 29, ['e'] = 30, ['f'] = 31,
    ['g'] = 32, ['h'] = 33, ['i'] = 34, ['j'] = 35, ['k'] = 36, ['l'] = 37,
    ['m'] = 38, ['n'] = 39, ['o'] = 40, ['p'] = 41, ['q'] = 42, ['r'] = 43,
    ['s'] = 44, ['t'] = 45, ['u'] = 46, ['v'] = 47, ['w'] = 48, ['x'] = 49,
    ['y'] = 50, ['z'] = 51,
    ['0'] = 52, ['1'] = 53, ['2'] = 54, ['3'] = 55, ['4'] = 56, ['5'] = 57,
    ['6'] = 58, ['7'] = 59, ['8'] = 60, ['9'] = 61,
    ['+'] = 62, ['/'] = 63,
};

static int is_b64_char(int c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
           (c >= '0' && c <= '9') || c == '+' || c == '/' || c == '=';
}

static int do_encode(FILE *fp) {
    unsigned char in[3];
    int col = 0;
    size_t n;

    while ((n = fread(in, 1, 3, fp)) > 0) {
        unsigned char out[4];
        out[0] = b64enc[in[0] >> 2];
        out[1] = b64enc[((in[0] & 0x03) << 4) | (n > 1 ? (in[1] >> 4) : 0)];
        out[2] = n > 1 ? b64enc[((in[1] & 0x0f) << 2) | (n > 2 ? (in[2] >> 6) : 0)] : '=';
        out[3] = n > 2 ? b64enc[in[2] & 0x3f] : '=';

        fwrite(out, 1, 4, stdout);
        col += 4;
        if (col >= 76) {
            putchar('\n');
            col = 0;
        }
    }

    if (col > 0)
        putchar('\n');

    return ferror(fp) ? 1 : 0;
}

static int do_decode(FILE *fp) {
    int c;
    unsigned char buf[4];
    int pos = 0;

    while ((c = fgetc(fp)) != EOF) {
        if (c == '\n' || c == '\r' || c == ' ')
            continue;
        if (!is_b64_char(c))
            continue;

        buf[pos++] = (unsigned char)c;
        if (pos == 4) {
            unsigned char a = b64dec[buf[0]], b = b64dec[buf[1]];
            unsigned char cc = b64dec[buf[2]], d = b64dec[buf[3]];

            putchar((a << 2) | (b >> 4));
            if (buf[2] != '=')
                putchar(((b & 0x0f) << 4) | (cc >> 2));
            if (buf[3] != '=')
                putchar(((cc & 0x03) << 6) | d);

            pos = 0;
        }
    }

    return ferror(fp) ? 1 : 0;
}

int main(int argc, char **argv) {
    int decode = 0;
    const char *filename = NULL;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--decode") == 0)
            decode = 1;
        else if (strcmp(argv[i], "-") == 0)
            filename = NULL; /* stdin */
        else
            filename = argv[i];
    }

    FILE *fp = stdin;
    if (filename) {
        fp = fopen(filename, "rb");
        if (!fp) {
            fprintf(stderr, "base64: %s: No such file or directory\n", filename);
            return 1;
        }
    }

    int rc = decode ? do_decode(fp) : do_encode(fp);

    if (fp != stdin)
        fclose(fp);

    return rc;
}
