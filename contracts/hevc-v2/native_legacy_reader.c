/* Offline decoder smoke: links unchanged l4desk json_min.c, no agent startup. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json_min.h"

static int check(const char *path, const char *expected_type) {
    char data[4096], value[128];
    int64_t version = 0;
    FILE *file = fopen(path, "rb");
    size_t length;
    if (!file) return 1;
    length = fread(data, 1, sizeof(data) - 1, file);
    if (ferror(file) || !feof(file)) { fclose(file); return 2; }
    fclose(file);
    data[length] = '\0';
    if (!json_extract_int64(data, "v", &version) || version != 1) return 3;
    if (!json_extract_str(data, "type", value, sizeof(value)) || strcmp(value, expected_type)) return 4;
    if (!json_extract_str(data, "sn", value, sizeof(value)) || strcmp(value, "hevc-fixture")) return 5;
    if (!json_extract_str(data, "lease_id", value, sizeof(value)) ||
        strcmp(value, "00000000-0000-4000-8000-000000000001")) return 6;
    if (!json_extract_str(data, "stream_instance_id", value, sizeof(value)) ||
        strcmp(value, "00000000-0000-4000-8000-000000000002")) return 7;
    if (!strcmp(expected_type, "stream_start")) {
        if (!json_extract_str(data, "profile", value, sizeof(value)) || strcmp(value, "low")) return 8;
        if (!json_extract_str(data, "mode", value, sizeof(value)) || strcmp(value, "desktop")) return 9;
    }
    if (!json_extract_int64(data, "expires_at_ms", &version) || version != 1792663210000LL) return 10;
    printf("PASS: unchanged native JSON decoder: %s\n", expected_type);
    return 0;
}

int main(int argc, char **argv) {
    int result;
    if (argc != 3) return 64;
    result = check(argv[1], "stream_start");
    if (result) return result;
    return check(argv[2], "stream_stop");
}
