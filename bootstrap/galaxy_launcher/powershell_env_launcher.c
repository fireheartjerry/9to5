/* Exact-environment launcher for the pinned Windows PowerShell boundary. */
#include <errno.h>
#include <process.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

static const wchar_t POWERSHELL[] =
    L"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";

static int clear_environment(void) {
    LPWCH block = GetEnvironmentStringsW();
    LPWCH entry;
    if (block == NULL) {
        return 0;
    }
    for (entry = block; *entry != L'\0'; entry += wcslen(entry) + 1) {
        wchar_t *separator;
        wchar_t *name;
        size_t length;
        if (*entry == L'=') {
            continue;
        }
        separator = wcschr(entry, L'=');
        if (separator == NULL || separator == entry) {
            FreeEnvironmentStringsW(block);
            return 0;
        }
        length = (size_t)(separator - entry);
        name = (wchar_t *)calloc(length + 1, sizeof(wchar_t));
        if (name == NULL) {
            FreeEnvironmentStringsW(block);
            return 0;
        }
        wmemcpy(name, entry, length);
        if (!SetEnvironmentVariableW(name, NULL)) {
            free(name);
            FreeEnvironmentStringsW(block);
            return 0;
        }
        free(name);
    }
    FreeEnvironmentStringsW(block);
    return 1;
}

int wmain(int argc, wchar_t **argv) {
    wchar_t **child_argv;
    int index;
    if (argc < 1 || !clear_environment() ||
        !SetEnvironmentVariableW(L"SystemRoot", L"C:\\Windows") ||
        !SetEnvironmentVariableW(L"WINDIR", L"C:\\Windows")) {
        return 78;
    }
    child_argv = (wchar_t **)calloc((size_t)argc + 1, sizeof(wchar_t *));
    if (child_argv == NULL) {
        return 78;
    }
    child_argv[0] = (wchar_t *)POWERSHELL;
    for (index = 1; index < argc; ++index) {
        child_argv[index] = argv[index];
    }
    child_argv[argc] = NULL;
    _wexecv(POWERSHELL, (const wchar_t *const *)child_argv);
    free(child_argv);
    return errno == 0 ? 78 : errno;
}
