import hmac
import hashlib
from datetime import datetime

# 必须和 license_verify.cpp 里的 static const char* SECRET 完全一致
SECRET = b"密码"

def generate_license(machine_id: str, expire_date: str):
    data = f"{machine_id}|{expire_date}".encode("utf-8")
    sig = hmac.new(SECRET, data, hashlib.sha256).hexdigest()

    with open("license.dat", "w", encoding="utf-8") as f:
        f.write(f"MachineID={machine_id}\n")
        f.write(f"Expire={expire_date}\n")
        f.write(f"Signature={sig}\n")

    print("license.dat 生成成功")
    print("到期时间:", expire_date)

if __name__ == "__main__":
    machine_id = input("输入 MachineID: ").strip()
    expire = input("输入到期日期 (YYYY-MM-DD): ").strip()

    # 简单校验
    datetime.strptime(expire, "%Y-%m-%d")

    generate_license(machine_id, expire)
