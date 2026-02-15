/*
 * crackme02 - XOR-Encoded Flag
 *
 * Difficulty: Easy-Medium
 * Goal: Recover the XOR-encoded flag
 * Flag: reagent{x0r_15_n0t_encrypt10n}
 *
 * The flag is XOR'd with a single-byte key (0x42) and stored in a
 * global array. The agent needs to find the XOR key and encoded data,
 * then recover the plaintext — either by reading the decompilation
 * or by running the binary dynamically.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define XOR_KEY 0x42

/* "reagent{x0r_15_n0t_encrypt10n}" XOR'd with 0x42 */
static unsigned char encoded[] = {
    0x30, 0x27, 0x23, 0x25, 0x27, 0x2c, 0x36, 0x39,  /* reagent{ */
    0x3a, 0x72, 0x30, 0x1d, 0x73, 0x77, 0x1d, 0x2c,  /* x0r_15_n */
    0x72, 0x36, 0x1d, 0x27, 0x2c, 0x21, 0x30, 0x3b,  /* 0t_encry */
    0x32, 0x36, 0x73, 0x72, 0x2c, 0x3f,               /* pt10n}   */
    0x00
};

static void decode(char *out, const unsigned char *data, size_t len) {
    for (size_t i = 0; i < len; i++) {
        out[i] = data[i] ^ XOR_KEY;
    }
    out[len] = '\0';
}

int verify(const char *input) {
    char flag[64];
    size_t len = sizeof(encoded) - 1;  /* exclude null terminator */
    decode(flag, encoded, len);
    return strcmp(input, flag) == 0;
}

int main(int argc, char *argv[]) {
    char buf[256];

    printf("=== CrackMe 02: XOR Challenge ===\n");
    printf("Enter the flag: ");
    fflush(stdout);

    if (argc > 1) {
        strncpy(buf, argv[1], sizeof(buf) - 1);
        buf[sizeof(buf) - 1] = '\0';
    } else {
        if (!fgets(buf, sizeof(buf), stdin)) {
            return 1;
        }
        buf[strcspn(buf, "\n")] = '\0';
    }

    if (verify(buf)) {
        printf("Correct! You decoded the flag.\n");
        return 0;
    } else {
        printf("Nope. The flag is XOR-encoded in the binary.\n");
        return 1;
    }
}
