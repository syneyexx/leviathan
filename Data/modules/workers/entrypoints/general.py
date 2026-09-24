from Data.modules.workers.entrypoints._cli import main_for_pool

def main() -> int:
    return main_for_pool("general")

if __name__ == "__main__":
    raise SystemExit(main())
