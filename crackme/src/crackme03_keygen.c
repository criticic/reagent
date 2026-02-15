/*
 * crackme03 - License Key Validator
 *
 * Difficulty: Medium
 * Goal: Understand the validation algorithm and generate a valid key
 * Valid key format: XXXX-XXXX-XXXX-XXXX (hex digits)
 * Example valid key: 1234-5678-9ABC-E242
 *
 * Validation rules:
 *   1. Format must be XXXX-XXXX-XXXX-XXXX (16 hex digits + 3 dashes)
 *   2. Sum of all hex digit values must be divisible by 16
 *   3. Group 4 XOR Group 2 must equal 0x1337
 *   4. Group 1 + Group 3 must have bit 0x8000 set
 *
 * The agent needs to reverse-engineer validate_key() and either find a
 * valid key or describe the algorithm.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

#define KEY_LEN 19  /* XXXX-XXXX-XXXX-XXXX */

static int parse_group(const char *s) {
    char tmp[5] = {0};
    memcpy(tmp, s, 4);
    return (int)strtol(tmp, NULL, 16);
}

static int hex_digit_sum(const char *key) {
    int sum = 0;
    for (int i = 0; i < KEY_LEN; i++) {
        if (key[i] != '-') {
            char c = toupper(key[i]);
            if (c >= '0' && c <= '9')
                sum += c - '0';
            else if (c >= 'A' && c <= 'F')
                sum += c - 'A' + 10;
        }
    }
    return sum;
}

int validate_key(const char *key) {
    /* Check length */
    if (strlen(key) != KEY_LEN)
        return 0;

    /* Check format: XXXX-XXXX-XXXX-XXXX */
    for (int i = 0; i < KEY_LEN; i++) {
        if (i == 4 || i == 9 || i == 14) {
            if (key[i] != '-') return 0;
        } else {
            if (!isxdigit(key[i])) return 0;
        }
    }

    int g1 = parse_group(key);
    int g2 = parse_group(key + 5);
    int g3 = parse_group(key + 10);
    int g4 = parse_group(key + 15);

    /* Rule 1: hex digit sum divisible by 16 */
    if (hex_digit_sum(key) % 16 != 0)
        return 0;

    /* Rule 2: g4 ^ g2 == 0x1337 */
    if ((g4 ^ g2) != 0x1337)
        return 0;

    /* Rule 3: (g1 + g3) must have bit 0x8000 set */
    if (((g1 + g3) & 0x8000) == 0)
        return 0;

    return 1;
}

int main(int argc, char *argv[]) {
    char buf[256];

    printf("=== CrackMe 03: License Key Validator ===\n");
    printf("Enter license key (XXXX-XXXX-XXXX-XXXX): ");
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

    if (validate_key(buf)) {
        printf("Valid license key! Product activated.\n");
        return 0;
    } else {
        printf("Invalid license key.\n");
        return 1;
    }
}
