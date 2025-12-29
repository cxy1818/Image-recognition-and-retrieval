#include <windows.h>
#include <wincrypt.h>
#include <intrin.h>
#include <iostream>
#include <string>

#pragma comment(lib, "advapi32.lib")

// 读取 Windows MachineGuid
std::string getMachineGuid() {
    HKEY hKey;
    char value[256];
    DWORD size = sizeof(value);

    if (RegOpenKeyExA(
            HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Cryptography",
            0,
            KEY_READ | KEY_WOW64_64KEY,
            &hKey) != ERROR_SUCCESS) {
        return "";
    }

    if (RegQueryValueExA(
            hKey,
            "MachineGuid",
            nullptr,
            nullptr,
            (LPBYTE)value,
            &size) != ERROR_SUCCESS) {
        RegCloseKey(hKey);
        return "";
    }

    RegCloseKey(hKey);
    return std::string(value);
}

// 获取 CPU ID
std::string getCpuId() {
    int cpuInfo[4] = {0};
    __cpuid(cpuInfo, 0);

    char buf[33];
    sprintf_s(buf, "%08X%08X%08X%08X",
              cpuInfo[0], cpuInfo[1], cpuInfo[2], cpuInfo[3]);
    return std::string(buf);
}

// SHA256（Windows CryptoAPI）
std::string sha256(const std::string& input) {
    HCRYPTPROV hProv = 0;
    HCRYPTHASH hHash = 0;
    BYTE hash[32];
    DWORD hashLen = 32;

    CryptAcquireContextA(&hProv, nullptr, nullptr,
                          PROV_RSA_AES, CRYPT_VERIFYCONTEXT);
    CryptCreateHash(hProv, CALG_SHA_256, 0, 0, &hHash);
    CryptHashData(hHash,
                  (BYTE*)input.c_str(),
                  (DWORD)input.size(),
                  0);
    CryptGetHashParam(hHash, HP_HASHVAL, hash, &hashLen, 0);

    CryptDestroyHash(hHash);
    CryptReleaseContext(hProv, 0);

    char hex[65];
    for (int i = 0; i < 32; i++)
        sprintf_s(hex + i * 2, 3, "%02x", hash[i]);
    hex[64] = 0;

    return std::string(hex);
}

int main() {
    std::string machineGuid = getMachineGuid();
    std::string cpuId = getCpuId();

    if (machineGuid.empty() || cpuId.empty()) {
        std::cout << "Failed to get hardware info\n";
        system("pause");
        return 1;
    }

    std::string raw = machineGuid + cpuId;
    std::string machineId = sha256(raw);

    std::cout << "Machine GUID:\n" << machineGuid << "\n\n";
    std::cout << "CPU ID:\n" << cpuId << "\n\n";
    std::cout << "Machine ID:\n" << machineId << "\n";

    system("pause");
    return 0;
}
