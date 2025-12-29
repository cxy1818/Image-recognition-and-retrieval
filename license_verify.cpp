#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <wincrypt.h>
#include <intrin.h>
#include <winhttp.h>
#include <bcrypt.h>
#include <string>
#include <fstream>
#include <sstream>
#include <vector>
#include <ctime>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "user32.lib")

#include <iostream>

// 配置

// ⚠️ 必须和 生成license脚本密码一致 
static const char* SECRET = "密码";

// 工具函数 

static std::string read_file(const char* path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return "";
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static std::string get_value(const std::string& text, const char* key) {
    size_t p = text.find(key);
    if (p == std::string::npos) return "";
    p += strlen(key);
    size_t e = text.find('\n', p);
    std::string val = text.substr(p, e - p);
    if (!val.empty() && val.back() == '\r') {
        val.pop_back();
    }
    return val;
}

// GET机器码 

// 获取 CPU ID
static std::string getCpuId() {
    int cpuInfo[4] = {0};
    __cpuid(cpuInfo, 0);
    char buf[33];
    sprintf_s(buf, "%08X%08X%08X%08X",
              cpuInfo[0], cpuInfo[1], cpuInfo[2], cpuInfo[3]);
    return std::string(buf);
}

// SHA256 
static std::string calc_sha256(const std::string& input) {
    HCRYPTPROV hProv = 0;
    HCRYPTHASH hHash = 0;
    BYTE hash[32];
    DWORD hashLen = 32;

    if (!CryptAcquireContextA(&hProv, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT)) return "";
    if (!CryptCreateHash(hProv, CALG_SHA_256, 0, 0, &hHash)) {
        CryptReleaseContext(hProv, 0);
        return "";
    }
    
    CryptHashData(hHash, (BYTE*)input.c_str(), (DWORD)input.size(), 0);
    CryptGetHashParam(hHash, HP_HASHVAL, hash, &hashLen, 0);

    CryptDestroyHash(hHash);
    CryptReleaseContext(hProv, 0);

    char hex[65];
    for (int i = 0; i < 32; i++)
        sprintf_s(hex + i * 2, 3, "%02x", hash[i]);
    hex[64] = 0;
    return std::string(hex);
}

static std::string get_machine_id() {
    HKEY hKey;
    char buf[256] = {};
    DWORD len = sizeof(buf);
    std::string machineGuid;

    if (RegOpenKeyExA(
        HKEY_LOCAL_MACHINE,
        "SOFTWARE\\Microsoft\\Cryptography",
        0,
        KEY_READ | KEY_WOW64_64KEY,
        &hKey) == ERROR_SUCCESS) {
        
        if (RegQueryValueExA(
            hKey,
            "MachineGuid",
            nullptr,
            nullptr,
            (LPBYTE)buf,
            &len) == ERROR_SUCCESS) {
            machineGuid = std::string(buf);
        }
        RegCloseKey(hKey);
    }

    std::string cpuId = getCpuId();

    if (machineGuid.empty() || cpuId.empty())
        return "";

    return calc_sha256(machineGuid + cpuId);
}

// HMAC-SHA256 (CNG)

static std::string hmac_sha256(const std::string& data) {
    BCRYPT_ALG_HANDLE hAlg = nullptr;
    BCRYPT_HASH_HANDLE hHash = nullptr;

    DWORD hashLen = 0;
    DWORD objLen = 0;
    DWORD cbData = 0;

    if (BCryptOpenAlgorithmProvider(
        &hAlg,
        BCRYPT_SHA256_ALGORITHM,
        nullptr,
        BCRYPT_ALG_HANDLE_HMAC_FLAG) != 0)
        return "";

    if (BCryptGetProperty(
        hAlg,
        BCRYPT_HASH_LENGTH,
        (PUCHAR)&hashLen,
        sizeof(hashLen),
        &cbData,
        0) != 0)
        return "";

    if (BCryptGetProperty(
        hAlg,
        BCRYPT_OBJECT_LENGTH,
        (PUCHAR)&objLen,
        sizeof(objLen),
        &cbData,
        0) != 0)
        return "";

    std::vector<BYTE> hashObject(objLen);
    std::vector<BYTE> hash(hashLen);

    if (BCryptCreateHash(
        hAlg,
        &hHash,
        hashObject.data(),
        objLen,
        (PUCHAR)SECRET,
        (ULONG)strlen(SECRET),
        0) != 0)
        return "";

    BCryptHashData(
        hHash,
        (PUCHAR)data.data(),
        (ULONG)data.size(),
        0);

    BCryptFinishHash(
        hHash,
        hash.data(),
        hashLen,
        0);

    BCryptDestroyHash(hHash);
    BCryptCloseAlgorithmProvider(hAlg, 0);

    static const char* hex = "0123456789abcdef";
    std::string out;
    for (BYTE b : hash) {
        out.push_back(hex[b >> 4]);
        out.push_back(hex[b & 0xF]);
    }
    return out;
}

// 网络时间

static bool http_get(const wchar_t* host, const wchar_t* path, std::string& response) {
    HINTERNET hSession = WinHttpOpen(
        L"license_verify/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0);
    if (!hSession) return false;

    HINTERNET hConnect = WinHttpConnect(
        hSession,
        host,
        INTERNET_DEFAULT_HTTPS_PORT,
        0);
    if (!hConnect) {
        WinHttpCloseHandle(hSession);
        return false;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect,
        L"GET",
        path,
        nullptr,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        WINHTTP_FLAG_SECURE);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    // 忽略 SSL 证书错误
    DWORD flags = SECURITY_FLAG_IGNORE_UNKNOWN_CA |
                  SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                  SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    WinHttpSetOption(hRequest, WINHTTP_OPTION_SECURITY_FLAGS, &flags, sizeof(flags));

    if (!WinHttpSendRequest(
            hRequest,
            WINHTTP_NO_ADDITIONAL_HEADERS,
            0,
            WINHTTP_NO_REQUEST_DATA,
            0,
            0,
            0) ||
        !WinHttpReceiveResponse(hRequest, nullptr)) {
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    DWORD size = 0;
    do {
        if (!WinHttpQueryDataAvailable(hRequest, &size)) break;
        if (size == 0) break;

        std::vector<char> buf(size + 1);
        DWORD read = 0;

        if (WinHttpReadData(hRequest, buf.data(), size, &read)) {
            response.append(buf.data(), read);
        }
    } while (size > 0);

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    return !response.empty();
}

static bool get_network_time(time_t& out) {
    std::string resp;

    // 1. Taobao API 
    resp.clear();
    if (http_get(L"api.m.taobao.com", L"/rest/api3.do?api=mtop.common.getTimestamp", resp)) {
        size_t pos = resp.find("\"t\":\"");
        if (pos != std::string::npos) {
            long long ms = _strtoi64(resp.c_str() + pos + 5, nullptr, 10);
            if (ms > 0) {
                out = (time_t)(ms / 1000);
                #ifdef BUILD_TEST
                std::cout << "[DEBUG] Taobao time: " << out << std::endl;
                #endif
                return true;
            }
        }
    }

    // 2. Suning API 
    resp.clear();
    if (http_get(L"quan.suning.com", L"/getSysTime.do", resp)) {
        size_t pos = resp.find("\"sysTime2\":\"");
        if (pos != std::string::npos) {
            std::string date_str = resp.substr(pos + 12, 19);
            int y, m, d, H, M, S;
            if (sscanf(date_str.c_str(), "%d-%d-%d %d:%d:%d", &y, &m, &d, &H, &M, &S) == 6) {
                std::tm tm = {};
                tm.tm_year = y - 1900;
                tm.tm_mon = m - 1;
                tm.tm_mday = d;
                tm.tm_hour = H;
                tm.tm_min = M;
                tm.tm_sec = S;
                out = _mkgmtime(&tm) - (8 * 3600);
                #ifdef BUILD_TEST
                std::cout << "[DEBUG] Suning time: " << out << std::endl;
                #endif
                return true;
            }
        }
    }

    //  WorldTimeAPI
    resp.clear();
    if (http_get(L"worldtimeapi.org", L"/api/timezone/Asia/Shanghai", resp)) {
        size_t pos = resp.find("\"unixtime\":");
        if (pos != std::string::npos) {
            out = (time_t)_strtoi64(resp.c_str() + pos + 11, nullptr, 10);
            #ifdef BUILD_TEST
            std::cout << "[DEBUG] WorldTimeAPI time: " << out << std::endl;
            #endif
            return true;
        }
    }

    return false;
}


// DLL 导出接口 

extern "C" __declspec(dllexport)
int VerifyLicense(char* out_expire, int out_len) {

    std::string lic = read_file("license.dat");
    if (lic.empty()) return 1;

    std::string mid = get_value(lic, "MachineID=");
    std::string exp = get_value(lic, "Expire=");
    std::string sig = get_value(lic, "Signature=");

    if (mid.empty() || exp.empty() || sig.empty())
        return 1;

    if (mid != get_machine_id()) {
        std::string msg = "MachineID mismatch!\nFile: " + mid + "\nReal: " + get_machine_id();
        MessageBoxA(NULL, msg.c_str(), "Debug", MB_OK);
        return 1;
    }

    std::string calc_sig = hmac_sha256(mid + "|" + exp);
    if (calc_sig != sig) {
        std::string msg = "Signature mismatch!\nFile: " + sig + "\nCalc: " + calc_sig + "\nData: " + mid + "|" + exp;
        MessageBoxA(NULL, msg.c_str(), "Debug", MB_OK);
        return 1;
    }

    time_t now;
    if (!get_network_time(now))
        return 1; // 网络时间获取失败，验证不通过

    std::tm tm{};
    sscanf(exp.c_str(), "%d-%d-%d",
           &tm.tm_year, &tm.tm_mon, &tm.tm_mday);
    tm.tm_year -= 1900;
    tm.tm_mon  -= 1;
    tm.tm_hour = 23;
    tm.tm_min  = 59;
    tm.tm_sec  = 59;

    time_t expire = _mkgmtime(&tm);

    strncpy(out_expire, exp.c_str(), out_len - 1);
    out_expire[out_len - 1] = 0;

    if (now > expire)
        return 2;

    return 0;
}

#ifdef BUILD_TEST
int main() {
    time_t now;
    if (get_network_time(now)) {
        std::cout << "Success! Network time: " << now << std::endl;
        std::cout << "Current local time: " << time(nullptr) << std::endl;
        return 0;
    } else {
        std::cout << "Failed to get network time." << std::endl;
        return 1;
    }
}
#endif

