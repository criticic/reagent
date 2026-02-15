/*
 * crackme05 - Multi-Stage Validator with Obfuscation
 *
 * Difficulty: Hard
 * Goal: Reverse-engineer the multi-stage validation and find the flag
 * Flag: reagent{m4th_plus_h4sh}
 *
 * This challenge uses:
 *   1. A custom hash function (FNV-1a) to verify the password
 *   2. Indirect function calls via a dispatch table
 *   3. Multiple validation stages that must all pass
 *   4. Arithmetic checks that obscure the logic
 *
 * The agent needs to understand the dispatch table, trace through
 * the stages, and reverse the hash/checks.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>

/* Custom hash — simple but not immediately obvious in decompilation */
static uint32_t custom_hash(const char *s) {
    uint32_t h = 0x811c9dc5;  /* FNV offset basis */
    while (*s) {
        h ^= (uint8_t)*s++;
        h *= 0x01000193;      /* FNV prime */
    }
    return h;
}

/* Stage 1: length must be exactly 23 (length of "reagent{m4th_plus_h4sh}") */
static int stage_length(const char *input) {
    int len = 0;
    const char *p = input;
    while (*p++) len++;
    /* Obfuscated comparison: len XOR 0x55 must equal 0x55 XOR 23 */
    return (len ^ 0x55) == (23 ^ 0x55);
}

/* Stage 2: must start with "reagent{" and end with "}" */
static int stage_wrapper(const char *input) {
    /* Check prefix byte-by-byte to avoid obvious string reference */
    if (input[0] != 'r') return 0;
    if (input[1] != 'e') return 0;
    if (input[2] != 'a') return 0;
    if (input[3] != 'g') return 0;
    if (input[4] != 'e') return 0;
    if (input[5] != 'n') return 0;
    if (input[6] != 't') return 0;
    if (input[7] != '{') return 0;

    int len = strlen(input);
    if (input[len - 1] != '}') return 0;

    return 1;
}

/* Stage 3: hash of the inner content must match */
static int stage_hash(const char *input) {
    /* Extract inner content (between { and }) */
    char inner[64] = {0};
    int len = strlen(input);
    if (len < 10) return 0;

    memcpy(inner, input + 8, len - 9);
    inner[len - 9] = '\0';

    /* Hash of "m4th_plus_h4sh" */
    uint32_t expected = 0x2d95cbe1;
    uint32_t got = custom_hash(inner);

    return got == expected;
}

/* Stage 4: character arithmetic check on inner content */
static int stage_arith(const char *input) {
    /* Sum of ASCII values of inner content modulo 256 must be 0x47 */
    int len = strlen(input);
    if (len < 10) return 0;

    unsigned int sum = 0;
    for (int i = 8; i < len - 1; i++) {
        sum += (unsigned char)input[i];
    }
    return (sum & 0xFF) == 0x76;
}

/* Dispatch table — makes control flow less obvious */
typedef int (*stage_fn)(const char *);

static stage_fn stages[] = {
    stage_length,
    stage_wrapper,
    stage_hash,
    stage_arith,
};

static const char *stage_names[] = {
    "length check",
    "format check",
    "hash check",
    "arithmetic check",
};

#define NUM_STAGES (sizeof(stages) / sizeof(stages[0]))

static int run_validation(const char *input) {
    for (unsigned int i = 0; i < NUM_STAGES; i++) {
        if (!stages[i](input)) {
            printf("  Stage %d (%s): FAILED\n", i + 1, stage_names[i]);
            return 0;
        }
        printf("  Stage %d (%s): PASSED\n", i + 1, stage_names[i]);
    }
    return 1;
}

int main(int argc, char *argv[]) {
    char buf[256];

    printf("=== CrackMe 05: Multi-Stage Validator ===\n");
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

    printf("Running validation...\n");
    if (run_validation(buf)) {
        printf("\nAll stages passed! Flag accepted.\n");
        return 0;
    } else {
        printf("\nValidation failed.\n");
        return 1;
    }
}
