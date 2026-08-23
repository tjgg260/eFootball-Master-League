// Pointer-drag for tactics tokens. Blazor owns the state; this only reports gestures:
//   drop  -> OnTokenDrop(slotIndex, leftPct, topPct, targetSlotOr-1)
//   click -> OnTokenClick(slotIndex)          (pointerup with < 6px movement)
window.tactics = (() => {
    let dotnet = null;
    let pitch = null;
    let dragging = null;   // { el, slot, startX, startY, origLeft, origTop, moved }

    function pctOf(el, clientX, clientY) {
        const r = pitch.getBoundingClientRect();
        const x = Math.min(Math.max(clientX - r.left, 0), r.width);
        const y = Math.min(Math.max(clientY - r.top, 0), r.height);
        return { left: (x / r.width) * 100, top: (y / r.height) * 100 };
    }

    function onDown(e) {
        const el = e.target.closest('.ttoken');
        if (!el || !pitch) return;
        e.preventDefault();
        el.setPointerCapture(e.pointerId);
        dragging = {
            el, slot: parseInt(el.dataset.slot, 10),
            startX: e.clientX, startY: e.clientY, moved: false,
        };
        el.classList.add('dragging');
    }

    function onMove(e) {
        if (!dragging) return;
        const dx = e.clientX - dragging.startX, dy = e.clientY - dragging.startY;
        if (Math.abs(dx) + Math.abs(dy) > 6) dragging.moved = true;
        if (!dragging.moved) return;
        const p = pctOf(dragging.el, e.clientX, e.clientY);
        dragging.el.style.left = p.left + '%';
        dragging.el.style.top = p.top + '%';
    }

    function onUp(e) {
        if (!dragging) return;
        const d = dragging;
        dragging = null;
        d.el.classList.remove('dragging');
        if (!d.moved) {
            dotnet.invokeMethodAsync('OnTokenClick', d.slot);
            return;
        }
        // hit-test another token under the pointer for a swap
        d.el.style.pointerEvents = 'none';
        const under = document.elementFromPoint(e.clientX, e.clientY);
        d.el.style.pointerEvents = '';
        const target = under ? under.closest('.ttoken') : null;
        const targetSlot = target && target !== d.el ? parseInt(target.dataset.slot, 10) : -1;
        const p = pctOf(d.el, e.clientX, e.clientY);
        dotnet.invokeMethodAsync('OnTokenDrop', d.slot, p.left, p.top, targetSlot);
    }

    return {
        init(dotnetRef) {
            this.dispose();
            dotnet = dotnetRef;
            pitch = document.getElementById('tacpitch');
            if (!pitch) return;
            pitch.addEventListener('pointerdown', onDown);
            pitch.addEventListener('pointermove', onMove);
            pitch.addEventListener('pointerup', onUp);
            pitch.addEventListener('pointercancel', onUp);
        },
        dispose() {
            if (!pitch) return;
            pitch.removeEventListener('pointerdown', onDown);
            pitch.removeEventListener('pointermove', onMove);
            pitch.removeEventListener('pointerup', onUp);
            pitch.removeEventListener('pointercancel', onUp);
            pitch = null; dotnet = null; dragging = null;
        },
    };
})();
