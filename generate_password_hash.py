import bcrypt
from getpass import getpass

def main():
    password = getpass("Enter a password to hash: ").strip()
    if not password:
        raise ValueError("Password cannot be empty.")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print("\nCopy this hash into app_config.json:")
    print(hashed)

if __name__ == "__main__":
    main()
