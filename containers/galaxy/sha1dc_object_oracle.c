/* Closed stdin-only Git object-ID oracle built from pinned SHA1DC source. */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "sha1.h"

#define GALAXY_MAX_OBJECT_BYTES 536870912ULL
#define GALAXY_BUFFER_BYTES 65536U

static const char *SHATTERED_PREFIX_HEX =
    "255044462d312e330a25e2e3cfd30a0a0a312030206f626a0a3c3c2f5769647468"
    "2032203020522f4865696768742033203020522f547970652034203020522f537562"
    "747970652035203020522f46696c7465722036203020522f436f6c6f725370616365"
    "2037203020522f4c656e6774682038203020522f42697473506572436f6d706f6e65"
    "6e7420383e3e0a73747265616d0affd8fffe00245348412d312069732064656164"
    "2121212121852fec092339759c39b1a1c63c4c97e1fffe017346dc9166b67e118f0"
    "29ab621b2560ff9ca67cca8c7f85ba84c79030c2b3de218f86db3a90901d5df45c1"
    "4f26fedfb3dc38e96ac22fe7bd728f0e45bce046d23c570feb141398bb552ef5a0a8"
    "2be331fea48037b8b5d71f0e332edf93ac3500eb4ddc0decc1a864790c782c762156"
    "60dd309791d06bd0af3f98cda4bc4629b1";

static int hex_nibble(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

static int decode_hex(const char *text, unsigned char *output, size_t output_size)
{
    size_t index;
    if (strlen(text) != output_size * 2U) return 0;
    for (index = 0; index < output_size; ++index) {
        int high = hex_nibble(text[index * 2U]);
        int low = hex_nibble(text[index * 2U + 1U]);
        if (high < 0 || low < 0) return 0;
        output[index] = (unsigned char)((high << 4) | low);
    }
    return 1;
}

static void print_digest(const unsigned char digest[20])
{
    size_t index;
    for (index = 0; index < 20U; ++index) printf("%02x", digest[index]);
    putchar('\n');
}

static int self_test(void)
{
    static const unsigned char expected_abc[20] = {
        0xa9, 0x99, 0x3e, 0x36, 0x47, 0x06, 0x81, 0x6a, 0xba, 0x3e,
        0x25, 0x71, 0x78, 0x50, 0xc2, 0x6c, 0x9c, 0xd0, 0xd8, 0x9d
    };
    unsigned char collision[320];
    unsigned char digest[20];
    SHA1_CTX context;
    int detected;

    if (!decode_hex(SHATTERED_PREFIX_HEX, collision, sizeof(collision))) return 70;
    SHA1DCInit(&context);
    SHA1DCSetSafeHash(&context, 1);
    SHA1DCSetUseDetectColl(&context, 1);
    SHA1DCUpdate(&context, (const char *)collision, sizeof(collision));
    detected = SHA1DCFinal(digest, &context);
    if (!detected) return 71;

    SHA1DCInit(&context);
    SHA1DCSetSafeHash(&context, 1);
    SHA1DCSetUseDetectColl(&context, 1);
    SHA1DCUpdate(&context, "abc", 3U);
    detected = SHA1DCFinal(digest, &context);
    if (detected || memcmp(digest, expected_abc, sizeof(digest)) != 0) return 72;
    puts("GALAXY_SHA1DC_SELF_TEST/v1 collision-detected normal-sha1-exact");
    return 0;
}

static int valid_type(const char *value)
{
    return strcmp(value, "blob") == 0 || strcmp(value, "tree") == 0 ||
           strcmp(value, "commit") == 0 || strcmp(value, "tag") == 0;
}

static int parse_size(const char *text, unsigned long long *value)
{
    char *end = NULL;
    unsigned long long parsed;
    if (text[0] == '\0' || (text[0] == '0' && text[1] != '\0')) return 0;
    errno = 0;
    parsed = strtoull(text, &end, 10);
    if (errno != 0 || end == NULL || *end != '\0' || parsed > GALAXY_MAX_OBJECT_BYTES)
        return 0;
    *value = parsed;
    return 1;
}

static int hash_object(const char *object_type, const char *size_text)
{
    unsigned char digest[20];
    char header[96];
    char buffer[GALAXY_BUFFER_BYTES];
    unsigned long long declared_size;
    unsigned long long remaining;
    int header_size;
    int detected;
    SHA1_CTX context;

    if (!valid_type(object_type) || !parse_size(size_text, &declared_size)) return 64;
    header_size = snprintf(header, sizeof(header), "%s %s", object_type, size_text);
    if (header_size < 1 || (size_t)header_size + 1U > sizeof(header)) return 65;
    header[header_size] = '\0';

    SHA1DCInit(&context);
    SHA1DCSetSafeHash(&context, 1);
    SHA1DCSetUseDetectColl(&context, 1);
    SHA1DCUpdate(&context, header, (size_t)header_size + 1U);
    remaining = declared_size;
    while (remaining > 0U) {
        size_t requested = remaining > sizeof(buffer) ? sizeof(buffer) : (size_t)remaining;
        size_t received = fread(buffer, 1U, requested, stdin);
        if (received != requested) return 66;
        SHA1DCUpdate(&context, buffer, received);
        remaining -= received;
    }
    if (ferror(stdin) || fgetc(stdin) != EOF) return 67;
    detected = SHA1DCFinal(digest, &context);
    if (detected) {
        fputs("sha1dc-collision-detected\n", stderr);
        return 78;
    }
    print_digest(digest);
    return ferror(stdout) ? 68 : 0;
}

int main(int argc, char **argv)
{
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
        _setmode(_fileno(stdout), _O_BINARY) == -1 ||
        _setmode(_fileno(stderr), _O_BINARY) == -1)
        return 69;
#endif
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("GALAXY_SHA1DC_OBJECT_ORACLE/v1 upstream=855827c583bc30645ba427885caa40c5b81764d2");
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--self-test") == 0) return self_test();
    if (argc == 4 && strcmp(argv[1], "hash-object") == 0)
        return hash_object(argv[2], argv[3]);
    fputs("usage: galaxy-sha1dc --version|--self-test|hash-object TYPE SIZE\n", stderr);
    return 64;
}
