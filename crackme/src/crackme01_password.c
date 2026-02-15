/*
 * crackme01 - Simple Password Check
 *
 * Difficulty: Easy
 * Goal: Find the hardcoded password
 * Flag: reagent{str1ngs_4re_e4sy}
 *
 * The password is compared with strcmp. An agent should find it
 * via strings analysis or decompilation.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const char *SECRET = "reagent{str1ngs_4re_e4sy}";

void success(void) {
    printf("Access granted! You found the flag.\n");
}

void failure(void) {
    printf("Wrong password. Try again.\n");
}

int check_password(const char *input) {
    return strcmp(input, SECRET) == 0;
}

int main(int argc, char *argv[]) {
    char buf[256];

    printf("=== CrackMe 01: Password Check ===\n");
    printf("Enter password: ");
    fflush(stdout);

    if (argc > 1) {
        strncpy(buf, argv[1], sizeof(buf) - 1);
        buf[sizeof(buf) - 1] = '\0';
    } else {
        if (!fgets(buf, sizeof(buf), stdin)) {
            return 1;
        }
        /* Strip newline */
        buf[strcspn(buf, "\n")] = '\0';
    }

    if (check_password(buf)) {
        success();
        return 0;
    } else {
        failure();
        return 1;
    }
}
