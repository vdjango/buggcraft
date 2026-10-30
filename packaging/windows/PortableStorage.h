/* Runs before Python/Qt: never unpack a portable launcher into a user profile. */
#if defined(_WIN32)
static bool buggcraftReadLocation(wchar_t *target, wchar_t const *program_dir, wchar_t const *name) {
    wchar_t filename[4096];
    if (swprintf(filename, 4096, L"%ls\\%ls", program_dir, name) < 0) return false;
    HANDLE file = CreateFileW(filename, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND;
    char bytes[16384]; DWORD count = 0;
    bool ok = ReadFile(file, bytes, sizeof(bytes) - 1, &count, NULL) && count > 0 && count < sizeof(bytes) - 1;
    CloseHandle(file);
    if (!ok) return false;
    bytes[count] = 0;
    int start = count >= 3 && (unsigned char)bytes[0] == 0xef && (unsigned char)bytes[1] == 0xbb && (unsigned char)bytes[2] == 0xbf ? 3 : 0;
    while (count > (DWORD)start && (bytes[count - 1] == '\n' || bytes[count - 1] == '\r' || bytes[count - 1] == ' ')) bytes[--count] = 0;
    wchar_t value[4096], combined[4096];
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes + start, -1, value, 4096) || !value[0]) return false;
    if (wcschr(value, L'\r') || wcschr(value, L'\n')) return false;
    if ((value[0] && value[1] == L':') || (value[0] == L'\\' && value[1] == L'\\')) {
        if (swprintf(combined, 4096, L"%ls", value) < 0) return false;
    } else if (swprintf(combined, 4096, L"%ls\\%ls", program_dir, value) < 0) return false;
    DWORD length = GetFullPathNameW(combined, 4096, target, NULL);
    return length > 0 && length < 4096;
}

static bool buggcraftPortableStorage(wchar_t *payload, wchar_t const *pattern) {
    wchar_t program_dir[4096], root[4096], temporary[4096], placeholder[4096];
    if (!GetModuleFileNameW(NULL, program_dir, 4096)) return false;
    stripFilenameW(program_dir);
    if (swprintf(root, 4096, L"%ls\\.buggcraft", program_dir) < 0) return false;
    if (!buggcraftReadLocation(root, program_dir, L"buggcraft-storage.txt") ||
        !buggcraftReadLocation(root, program_dir, L"buggcraft-storage.pending")) return false;
    if (swprintf(temporary, 4096, L"%ls\\temp", root) < 0 ||
        swprintf(placeholder, 4096, L"%ls\\.directory", temporary) < 0 ||
        !createContainingDirectory(placeholder)) return false;
    SetEnvironmentVariableW(L"TEMP", temporary);
    SetEnvironmentVariableW(L"TMP", temporary);
    SetEnvironmentVariableW(L"TMPDIR", temporary);
    wchar_t const *tag = wcsrchr(pattern, L'/');
    wchar_t const *backslash = wcsrchr(pattern, L'\\');
    if (backslash && (!tag || backslash > tag)) tag = backslash;
    if (!tag || !tag[1]) return false;
    return swprintf(payload, 4096, L"%ls\\runtime\\Buggcraft\\%ls", root, tag + 1) > 0;
}
#endif
