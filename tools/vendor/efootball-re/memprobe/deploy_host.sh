#!/usr/bin/env bash
# 把新编的宿主 (dxgi.dll) 装进游戏目录。
#
# 和 hot.sh 的区别: 插件 (sider_tools.dll) 可以热换, 宿主不行 —— 游戏从 dxgi.dll
# 导入符号, 所以它整场都被锁住。**必须先完全退出游戏再跑这个**, 跑完再启动游戏。
#
#   ./deploy_host.sh
#
# 装完哪些钩子由游戏目录里的开关文件决定 (两个位置都要有, 游戏启动后会改工作目录):
#   attrhook.on   属性改写钩子   (set_attrs.ps1 配合 attrhook.mode 用)
#   statshook.on  比赛统计定位钩子 (只读; 进比赛后日志里看 [STATSHOOK] ★ 那行)
set -u

REPO="$(cd "$(dirname "$0")" && pwd)"
GAME="${EFOOTBALL_DIR:-/c/Program Files (x86)/Steam/steamapps/common/eFootball}"
# 游戏 exe 在 Binaries\Win64, Windows 从 exe 所在目录找 dxgi.dll —— 装进根目录等于没装。
# 2026-09-13 之前这里写的是 "$GAME/dxgi.dll", 结果 statshook 那版宿主从来没进过游戏。
DEST="$GAME/eFootball/Binaries/Win64"
BACKUP="${EFOOTBALL_DXGI_BACKUP:-$HOME/Backups/eFootball/dxgi}"

if tasklist 2>/dev/null | grep -qi "eFootball.exe"; then
    echo "游戏还在运行 —— dxgi.dll 被锁住, 换不了。先完全退出游戏。"
    exit 1
fi

cd "$REPO/host" || exit 1
echo "编译宿主..."
if ! cargo build --release 2>&1 | tail -2; then
    echo "编译失败, 没有动游戏目录里的任何东西"
    exit 1
fi

SRC="$REPO/host/target/release/dxgi.dll"
[ -f "$SRC" ] || { echo "找不到 $SRC"; exit 1; }

# 覆盖前把正在用的那份留一份, 按时间戳命名 —— 新宿主出事时直接拷回去。
# BACKUP 里的 dxgi.dll.before_attrhook 是更早的原件, 永远不覆盖它。
if [ -f "$DEST/dxgi.dll" ]; then
    mkdir -p "$BACKUP"
    STAMP=$(date +%Y%m%d_%H%M%S)
    cp "$DEST/dxgi.dll" "$BACKUP/dxgi.dll.replaced_$STAMP" && echo "已备份当前 dxgi.dll -> $BACKUP/dxgi.dll.replaced_$STAMP"
fi

if ! cp "$SRC" "$DEST/dxgi.dll"; then
    echo "复制失败 (权限? 游戏真的退干净了吗?)"
    exit 1
fi
echo "已装: $DEST/dxgi.dll"

# 插件顺手也更新一遍, 免得宿主和插件版本对不上。
if [ -f "$REPO/plugin/target/release/sider_tools.dll" ]; then
    for d in "$GAME" "$GAME/eFootball/Binaries/Win64"; do
        cp "$REPO/plugin/target/release/sider_tools.dll" "$d/sider_tools.dll" 2>/dev/null
    done
    echo "插件也已同步到两个位置"
fi

echo
echo "开关文件:"
for f in attrhook.on statshook.on; do
    for d in "$GAME" "$GAME/eFootball/Binaries/Win64"; do
        [ -f "$d/$f" ] && echo "  有  $d/$f"
    done
done
echo
echo "现在可以启动游戏了。"
