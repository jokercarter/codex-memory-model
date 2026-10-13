"""Copy the canonical, data-free source modules into the distributable plugin."""
from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = ("codex_memory_core.py", "codex_memory_features.py", "codex_memory_dashboard.py",
         "codex_memory_mcp.py", "codex_memory_hook.py", "codex_memory_vault.pyw")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report drift without writing files")
    parser.add_argument("--installed-plugin", type=Path, help="Also synchronize runtime, skill and settings into an already installed local plugin directory")
    parser.add_argument("--installed-skill-dir", type=Path, help="Also update the standalone Codex skill directory")
    parser.add_argument("--hook-runtime", type=Path, help="Also synchronize the shared storage module used by an already configured lifecycle hook")
    args = parser.parse_args()
    pairs = [(ROOT / name, ROOT / "plugins/codex-memory/runtime" / name) for name in FILES]
    pairs += [(ROOT / "skills/codex-memory/SKILL.md", ROOT / "plugins/codex-memory/skills/codex-memory/SKILL.md"),
              (ROOT / "config/memory-settings.json.example", ROOT / "plugins/codex-memory/config/memory-settings.json.example")]
    if args.installed_plugin:
        plugin=args.installed_plugin.expanduser()
        if not (plugin/".codex-plugin"/"plugin.json").is_file():
            parser.error(f"installed plugin manifest not found at {plugin}")
        pairs += [(ROOT/name,plugin/"runtime"/name) for name in FILES]
        pairs += [(ROOT/"plugins/codex-memory/.mcp.json",plugin/".mcp.json")]
        pairs += [(ROOT/"skills/codex-memory/SKILL.md",plugin/"skills/codex-memory/SKILL.md"),
                  (ROOT/"skills/codex-memory/agents/openai.yaml",plugin/"skills/codex-memory/agents/openai.yaml"),
                  (ROOT/"config/memory-settings.json.example",plugin/"config/memory-settings.json.example")]
    if args.installed_skill_dir:
        skill=args.installed_skill_dir.expanduser()
        pairs += [(ROOT/"skills/codex-memory/SKILL.md",skill/"SKILL.md"),
                  (ROOT/"skills/codex-memory/agents/openai.yaml",skill/"agents/openai.yaml")]
    if args.hook_runtime:
        pairs += [(ROOT/"codex_memory_core.py",args.hook_runtime.expanduser()/"codex_memory_core.py")]
    missing = [str(src) for src, _ in pairs if not src.is_file()]
    if missing:
        parser.error("incomplete canonical source: " + ", ".join(missing))
    drift = [(src, dst) for src, dst in pairs if not dst.exists() or src.read_bytes() != dst.read_bytes()]
    if args.check:
        for _, dst in drift:
            print("out of sync:", dst)
        raise SystemExit(bool(drift))
    for src, dst in drift:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print("synced:", dst)

if __name__ == "__main__":
    main()
