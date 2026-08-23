using Microsoft.AspNetCore.Components;
using Microsoft.JSInterop;
using ML.App;
using ML.Web.Data;

namespace ML.Web.Pages;

public partial class Tactics : ComponentBase, IDisposable
{
    [Inject] public GameHost Game { get; set; } = default!;
    [Inject] public Db Db { get; set; } = default!;
    [Inject] public IJSRuntime JS { get; set; } = default!;

    // ---------- types ----------
    protected enum Tab { Lineup, TacticsTab, Team }
    protected enum TMenu { Formation, Playstyle, Instructions }

    protected sealed class Pl
    {
        public int PlayerId;
        public int Shirt;
        public string Name = "";
        public int Rating;
        public string Registered = "CMF";
        public IReadOnlyList<string> Learned = Array.Empty<string>();
        public string? Face;
        public int Height;
        public int Weight;
        public int Age;
        public string Surname => Name.Contains(' ') ? Name[(Name.LastIndexOf(' ') + 1)..] : Name;
    }

    protected sealed record Tok(int Slot, int PlayerId, int Shirt, string Name, int Rating,
        string Position, double Left, double Top, string? Face, int Height, int Weight, int Age)
    {
        public string Surname => Name.Contains(' ') ? Name[(Name.LastIndexOf(' ') + 1)..] : Name;
    }

    protected sealed record BenchP(int PlayerId, int Shirt, string Name, string Position, int Rating, string? Face)
    {
        public string Surname => Name.Contains(' ') ? Name[(Name.LastIndexOf(' ') + 1)..] : Name;
    }

    protected sealed record OppTok(double Left, double Top, string Position, int Rating, string Surname);
    protected sealed record OppSub(string Position, string Name);
    protected sealed record StyleDef(string Name, string[] Pages);
    protected sealed record InstrOption(string Name, string Description);
    protected sealed record Duty(string Kind, string Label);

    // ---------- catalogs (game-verbatim, from the shared engine's WPF layer) ----------
    protected static readonly StyleDef[] StyleCatalog =
    {
        new("Possession Game", new[]
        {
            "Sends a few players near the ball to achieve numerical superiority across a small area, then uses short passes to break through the opposing defence.",
            "Shifts the entire team towards the same side as the ball and defends with a tight, compact shape.\nWhen the ball is high up the pitch, the entire team presses aggressively.",
            "When winning possession, nearby teammates provide support and priority is placed on keeping possession. When winning the ball high up the pitch, or when playing a forward pass immediately after regaining possession, a counterattack will be launched.",
            "When ball possession is lost, nearby players will aggressively pressure the opponent in numbers to try and regain possession.",
        }),
        new("Quick Counter", new[]
        {
            "Players will spring a counter attack by actively dashing towards the opponent's goal.",
            "Keep a high defensive line to put pressure on the opponent from the frontlines.",
            "When ball possession is regained close to the opponent's goal, the players will immediately dash towards the goal to enable a counter attack.",
            "When ball possession is lost, nearby players will aggressively pressure the opponent in numbers to try and regain possession.",
        }),
        new("Long Ball Counter", new[]
        {
            "After stealing possession deep inside your own half, your players rush forward into open spaces enabling you to orchestrate a quick counter attack.",
            "Players form a deep-sitting defensive line near the goal and defend from there.",
            "After losing possession, players sprint back to their own half and line up in a defensive formation.",
        }),
        new("Long Ball", new[]
        {
            "Players will focus on long balls, rather than trying to dominate the midfield.\nThey will prepare to receive long passes, and the surrounding players will also position themselves to pick up second balls if needed.",
            "The defensive block will be kept deep to ensure a steady defense.",
            "When ball possession is regained, defenders will fall back to a supportive position, while the attacking players will position themselves to receive a long ball.",
            "When ball possession is lost, players will fall back to form a defensive block as soon as possible.",
        }),
        new("Out Wide", new[]
        {
            "Players will focus on attacking down the flanks and crossing the ball to create goalscoring opportunities.\nWhen players notice the ball is in a good position to be crossed into the area, they will dash into position to try and score a goal.",
            "The defensive block will be focused in the midfield, allowing players to adapt to the game state with ease.",
            "When ball possession is regained, players will tend to open wide to the sides.\nEven those who are positioned in the centre of the pitch will slide a bit to the sides to provide support.",
            "When ball possession is lost, players will focus on forming a defensive block in the midfield, then adapt their formation according to the game state.",
        }),
        new("Overload", new[]
        {
            "Players concentrate on the same side as the ball to achieve numerical superiority.\nIn attack this makes short passes easier and lets the team keep possession even in crowded areas, breaking lines with quick combinations.",
            "Without the ball the team stays compact and closes the ball-carrier down quickly, raising the back line for a high press when attacking in the opponent's half.",
            "When possession is regained, nearby players swarm the ball side to rebuild the overload and keep the ball moving through tight spaces.",
            "When possession is lost, players immediately gegenpress — hunting the ball in numbers to win it back high up the pitch.",
        }),
    };

    protected static readonly InstrOption[] AttackInstrOptions =
    {
        new("Off", "No individual attacking instruction."),
        new("Defensive", "The instructed player will refrain from pushing forward in attack."),
        new("Anchoring", "The instructed player is restricted from drifting out of position horizontally."),
    };

    protected static readonly InstrOption[] DefenceInstrOptions =
    {
        new("Off", "No individual defensive instruction."),
        new("Tight Marking", "The selected opposition player will be marked much tighter than usual, with the marker switching depending on the position."),
        new("Man Marking", "The instructed player will perform a tighter man marking on his target."),
        new("Counter Target", "The instructed player will stay in the vicinity of the opposition's box rather than dropping back to help the defence."),
    };

    protected static readonly string[] InstrSlots = { "attack1", "attack2", "defence1", "defence2" };
    protected static readonly string[] AutoSubOptions = { "Off", "Very Late", "Flexible", "Very Early" };

    protected static readonly Duty[] DutyList =
    {
        new("cap", "Captain"), new("fk", "Free kicks"), new("pk", "Penalties"),
        new("ckl", "Corners L"), new("ckr", "Corners R"),
    };

    private static readonly (string Key, string Label)[] AbilityCatalog =
    {
        ("offensive_awareness", "Off. Awareness"), ("ball_control", "Ball Control"),
        ("dribbling", "Dribbling"), ("tight_possession", "Tight Possession"),
        ("low_pass", "Low Pass"), ("lofted_pass", "Lofted Pass"), ("finishing", "Finishing"),
        ("heading", "Heading"), ("set_piece_taking", "Set Piece Taking"), ("curl", "Curl"),
        ("speed", "Speed"), ("acceleration", "Acceleration"), ("kicking_power", "Kicking Power"),
        ("jumping", "Jumping"), ("physical_contact", "Physical Contact"), ("balance", "Balance"),
        ("stamina", "Stamina"), ("defensive_awareness", "Def. Awareness"), ("tackling", "Tackling"),
        ("aggression", "Aggression"), ("defensive_engagement", "Def. Engagement"),
        ("gk_awareness", "GK Awareness"), ("gk_catching", "GK Catching"),
        ("gk_parrying", "GK Parrying"), ("gk_reflexes", "GK Reflexes"), ("gk_reach", "GK Reach"),
    };

    // ---------- state ----------
    protected Tab _tab = Tab.Lineup;
    protected TMenu _tmenu = TMenu.Formation;
    protected int _teamMenu;
    protected int _phase;
    protected int _stylePage;
    protected string _instrSlot = "attack1";
    protected int _hover;
    protected int? _details;
    protected int _sel = -1;
    protected int _benchSel = -1;
    protected int _styleIx;
    protected string _autoSub = "Flexible";
    protected int _hoverFid;
    protected string _shape = "—";
    protected string _oppShape = "";
    protected string _oppName = "Next opponent";
    protected string _status = "Drag players to reposition — their position follows where you put them.";

    protected readonly Dictionary<string, int?> _duties = new();
    private readonly Dictionary<string, (string Name, int Pid)> _instr = new();
    protected List<(string Shape, int Id)> _templates = new();
    private readonly List<Pl> _ids = new();
    private readonly List<(double Adv, double Wid, string Pos)>[] _geom =
        { new List<(double, double, string)>(), new List<(double, double, string)>() };
    protected readonly List<BenchP> _bench = new();
    protected readonly List<OppTok> _opp = new();
    protected readonly List<OppSub> _oppSubs = new();
    private readonly Dictionary<int, (int Fatigue, bool Injured)> _cond = new();
    private readonly Dictionary<int, Dictionary<string, int>> _abil = new();
    private DotNetObjectReference<Tactics>? _selfRef;

    // ---------- init ----------
    protected override void OnInitialized()
    {
        if (Game.Session is not { } s) return;

        var tactics = s.Repo.TeamTactics(s.CurrentTeamId);
        _styleIx = Math.Clamp(tactics.FirstOrDefault(t => t.Phase == 0)?.Style ?? 0, 0, StyleCatalog.Length - 1);
        _autoSub = s.GetSetting($"autosub_{s.CurrentTeamId}") ?? "Flexible";
        _templates = s.FormationOptions().GroupBy(f => f.Shape).Select(g => g.First())
            .OrderBy(f => f.Shape).ToList();

        var (fid0, fid1) = s.OwnFormationIds();
        LoadGeom(0, fid0);
        LoadGeom(1, fid1);
        if (_geom[1].Count != _geom[0].Count) { _geom[1].Clear(); _geom[1].AddRange(_geom[0]); }

        var squad = s.Squad().OrderBy(x => x.Slot.Slot).ToList();
        for (var i = 0; i < _geom[0].Count && i < squad.Count; i++)
        {
            var (p, sl) = squad[i];
            _ids.Add(NewPl(p, sl.SquadNumber));
        }
        while (_ids.Count < _geom[0].Count) _ids.Add(new Pl());
        foreach (var (p, sl) in squad.Skip(_geom[0].Count))
            _bench.Add(new BenchP(p.Id, sl.SquadNumber, p.Name, p.Position, p.OverallRating ?? 0, FaceOf(p.Id)));

        _duties["cap"] = s.Captain;
        foreach (var k in new[] { "fk", "pk", "ckl", "ckr" }) _duties[k] = s.TakerOf(k);
        foreach (var slot in InstrSlots)
        {
            var raw = s.InstructionOf(slot);
            var parts = raw.Split('|');
            _instr[slot] = (parts[0] is { Length: > 0 } n ? n : "Off",
                parts.Length > 1 && int.TryParse(parts[1], out var pid) ? pid : 0);
        }

        var md = s.NextFixture()?.Matchday ?? 0;
        foreach (var c in s.Repo.ConditionsFor(s.CurrentTeamId))
            _cond[c.PlayerId] = (c.Fatigue, c.InjuredUntilMd is { } u && u >= md);

        LoadOpponent(s);
        UpdateShape();
        _hover = _ids.FirstOrDefault(p => p.PlayerId > 0)?.PlayerId ?? 0;
    }

    private Pl NewPl(ML.Data.PlayerRow p, int shirt)
    {
        var bio = Db.Bio(p.Id);
        return new Pl
        {
            PlayerId = p.Id, Shirt = shirt, Name = p.Name, Rating = p.OverallRating ?? 0,
            Registered = p.Position, Learned = Game.Session!.LearnedPositions(p.Id),
            Face = FaceOf(p.Id), Height = bio.HeightCm, Weight = bio.WeightKg, Age = bio.Age,
        };
    }

    private string? FaceOf(long pid) => Db.Bio(pid).FacePath;

    private void LoadGeom(int phase, int fid)
    {
        _geom[phase].Clear();
        if (Game.Session is not { } s) return;
        foreach (var sl in s.Repo.FormationSlots(fid).OrderBy(x => x.SlotIndex))
        {
            var adv = (sl.Y - 3) / 40.0 * 100;
            var wid = (sl.X - 12) / 80.0 * 100;
            _geom[phase].Add((Math.Clamp(adv, 0, 100), Math.Clamp(wid, 0, 100),
                ML.App.Visuals.RoleCodeLabel(sl.Position)));
        }
    }

    private void LoadOpponent(Session s)
    {
        var next = s.NextFixture();
        if (next is null) return;
        var oppId = next.HomeTeamId == s.CurrentTeamId ? next.AwayTeamId : next.HomeTeamId;
        _oppName = s.TeamName(oppId);
        try { s.PickBestXiAndTactic(oppId, s.CurrentTeamId); } catch { /* preview only */ }
        var fid = s.Repo.TeamTactics(oppId).FirstOrDefault(t => t.Phase == 0)?.FormationId;
        if (fid is null) return;
        var slots = s.Repo.FormationSlots(fid.Value).OrderBy(x => x.SlotIndex).ToList();
        var xi = s.Repo.SquadPlayers(oppId).Take(slots.Count).ToList();
        // fill slots position-aware: the GK mans the GK slot, outfielders match by unit
        var assign = new ML.Data.PlayerRow?[slots.Count];
        var pool = xi.ToList();
        string SlotPos(int i) => ML.App.Visuals.RoleCodeLabel(slots[i].Position);
        for (var pass = 0; pass < 2; pass++)
        {
            for (var i = 0; i < slots.Count; i++)
            {
                if (assign[i] is not null) continue;
                var wantCat = ML.App.Visuals.PositionCategory(SlotPos(i));
                var pick = pass == 0
                    ? pool.FirstOrDefault(p => ML.App.Visuals.PositionCategory(p.Position) == wantCat)
                    : pool.FirstOrDefault();
                if (pick is not null) { assign[i] = pick; pool.Remove(pick); }
            }
        }
        for (var i = 0; i < slots.Count; i++)
        {
            var adv = (slots[i].Y - 3) / 40.0 * 100;
            var wid = (slots[i].X - 12) / 80.0 * 100;
            var pl = assign[i];
            var nm = pl?.Name ?? "";
            _opp.Add(new OppTok(
                98 - Math.Clamp(adv, 0, 100) * 0.46,
                8 + Math.Clamp(wid, 0, 100) * 0.84,
                SlotPos(i),
                pl?.OverallRating ?? 0,
                nm.Contains(' ') ? nm[(nm.LastIndexOf(' ') + 1)..] : nm));
        }
        foreach (var pl in s.Repo.SquadPlayers(oppId).Skip(slots.Count).Take(12))
            _oppSubs.Add(new OppSub(pl.Position, pl.Name));
        try { _oppShape = Formations.ShapeOf(slots.Select(x => x.Y)); } catch { _oppShape = ""; }
    }

    // ---------- JS drag ----------
    protected override async Task OnAfterRenderAsync(bool first)
    {
        if (Game.Session is null) return;
        if (_tab == Tab.Lineup || (_tab == Tab.TacticsTab && _tmenu == TMenu.Formation))
        {
            _selfRef ??= DotNetObjectReference.Create(this);
            await JS.InvokeVoidAsync("tactics.init", _selfRef);
        }
    }

    public void Dispose()
    {
        _ = JS.InvokeVoidAsync("tactics.dispose");
        _selfRef?.Dispose();
    }

    [JSInvokable]
    public void OnTokenClick(int slot)
    {
        if (slot < 0 || slot >= _ids.Count) return;
        if (_benchSel >= 0) { SwapWithBench(slot); return; }
        _sel = slot;
        _hover = _ids[slot].PlayerId;
        StateHasChanged();
    }

    [JSInvokable]
    public void OnTokenDrop(int slot, double leftPct, double topPct, int targetSlot)
    {
        if (slot < 0 || slot >= _ids.Count) return;
        if (targetSlot >= 0 && targetSlot < _ids.Count && targetSlot != slot)
        {
            (_ids[slot], _ids[targetSlot]) = (_ids[targetSlot], _ids[slot]);
            _status = $"{_ids[targetSlot].Name} and {_ids[slot].Name} switch positions.";
        }
        else
        {
            var adv = Math.Clamp((leftPct - 2) / 0.46, 0, 100);
            var wid = Math.Clamp((topPct - 8) / 0.84, 0, 100);
            var pos = PositionAt(adv, wid);
            var old = _geom[_phase][slot];
            _geom[_phase][slot] = (adv, wid, pos);
            if (pos != old.Pos) _status = $"{_ids[slot].Surname} now plays {pos}.";
            _sel = slot;
        }
        UpdateShape();
        StateHasChanged();
    }

    protected static string PositionAt(double adv, double width)
    {
        var l = width < 28; var r = width > 72;
        return adv switch
        {
            < 12 => "GK",
            < 35 => l ? "LB" : r ? "RB" : "CB",
            < 47 => l ? "LMF" : r ? "RMF" : "DMF",
            < 62 => l ? "LMF" : r ? "RMF" : "CMF",
            < 76 => l ? "LWF" : r ? "RWF" : "AMF",
            _ => l ? "LWF" : r ? "RWF" : adv >= 88 ? "CF" : "SS",
        };
    }

    // ---------- tokens ----------
    protected IEnumerable<Tok> Tokens(int phase)
    {
        for (var i = 0; i < _ids.Count && i < _geom[phase].Count; i++)
        {
            var g = _geom[phase][i];
            var p = _ids[i];
            yield return new Tok(i, p.PlayerId, p.Shirt, p.Name, p.Rating, g.Pos,
                2 + g.Adv * 0.46, 8 + g.Wid * 0.84, p.Face, p.Height, p.Weight, p.Age);
        }
    }

    protected Tok? HoverTok()
        => Tokens(_phase).FirstOrDefault(t => t.PlayerId == _hover)
           ?? BenchTok(_hover)
           ?? Tokens(_phase).FirstOrDefault(t => t.PlayerId > 0);

    private Tok? BenchTok(int pid)
    {
        var b = _bench.FirstOrDefault(x => x.PlayerId == pid);
        if (b is null) return null;
        var bio = Db.Bio(b.PlayerId);
        return new Tok(-1, b.PlayerId, b.Shirt, b.Name, b.Rating, b.Position, 0, 0, b.Face,
            bio.HeightCm, bio.WeightKg, bio.Age);
    }

    protected Tok? DetailTok(int pid)
        => Tokens(_phase).FirstOrDefault(t => t.PlayerId == pid) ?? BenchTok(pid);

    protected void BenchClick(int ix) => _benchSel = _benchSel == ix ? -1 : ix;

    private void SwapWithBench(int slot)
    {
        if (Game.Session is not { } s) return;
        var t = _ids[slot];
        var b = _bench[_benchSel];
        _bench[_benchSel] = new BenchP(t.PlayerId, t.Shirt, t.Name, t.Registered, t.Rating, t.Face);
        var bio = Db.Bio(b.PlayerId);
        _ids[slot] = new Pl
        {
            PlayerId = b.PlayerId, Shirt = b.Shirt, Name = b.Name, Rating = b.Rating,
            Registered = b.Position, Learned = s.LearnedPositions(b.PlayerId), Face = b.Face,
            Height = bio.HeightCm, Weight = bio.WeightKg, Age = bio.Age,
        };
        _benchSel = -1;
        _sel = slot;
        _status = $"{_ids[slot].Name} comes into the XI.";
        StateHasChanged();
    }

    // ---------- tabs / phase ----------
    protected void SetTab(Tab t) { _tab = t; _sel = -1; _benchSel = -1; }
    protected void TogglePhase() { _phase = _phase == 0 ? 1 : 0; UpdateShape(); }

    private void UpdateShape()
    {
        try { _shape = Formations.ShapeOf(_geom[_phase].Select(g => (int)Math.Round(3 + g.Adv / 100 * 40))); }
        catch { _shape = "—"; }
    }

    // ---------- formation templates ----------
    protected void PreviewTemplate(int fid)
    {
        _hoverFid = fid;
        LoadGeom(_phase, fid);
        UpdateShape();
    }

    protected void ApplyTemplate(int fid)
    {
        if (Game.Session is not { } s) return;
        _hoverFid = fid;
        LoadGeom(_phase, fid);
        // position-aware reassignment: GK stays in the GK slot; outfielders re-queue by unit
        var gkSlot = _geom[_phase].FindIndex(g => g.Pos == "GK");
        var gk = _ids.FirstOrDefault(p => ML.App.Visuals.PositionCategory(p.Registered) == "GK" && p.PlayerId > 0);
        var outfield = _ids.Where(p => p != gk).ToList();
        var newIds = new List<Pl>();
        for (var i = 0; i < _geom[_phase].Count; i++)
        {
            if (i == gkSlot && gk is not null) { newIds.Add(gk); continue; }
            var want = ML.App.Visuals.PositionCategory(_geom[_phase][i].Pos);
            var pick = outfield.FirstOrDefault(p => ML.App.Visuals.PositionCategory(p.Registered) == want)
                       ?? outfield.FirstOrDefault();
            if (pick is not null) { newIds.Add(pick); outfield.Remove(pick); }
            else newIds.Add(new Pl());
        }
        _ids.Clear();
        _ids.AddRange(newIds);
        UpdateShape();
        _status = $"Formation set to {_shape} — players re-slotted by position.";
    }

    // ---------- playstyle ----------
    protected void PickStyle(int ix) { _styleIx = ix; _stylePage = 0; }

    protected string PageTitle(int page)
    {
        var titles = StyleCatalog[_styleIx].Pages.Length == 3
            ? new[] { "In possession", "Out of possession", "On losing the ball" }
            : new[] { "In possession", "Out of possession", "On winning the ball", "On losing the ball" };
        return titles[Math.Clamp(page, 0, titles.Length - 1)];
    }

    private (int X, int Y, int W, int H) Zone()
    {
        // rough block zones per style+page on the 300x190 mini pitch (own goal left)
        return (_styleIx, _stylePage) switch
        {
            (0, 0) => (110, 20, 110, 150), (0, 1) => (80, 40, 100, 110), (0, 2) => (120, 30, 110, 130), (0, 3) => (150, 30, 110, 130),
            (1, 0) => (180, 20, 100, 150), (1, 1) => (120, 25, 110, 140), (1, 2) => (190, 30, 100, 130), (1, 3) => (150, 30, 110, 130),
            (2, 0) => (40, 30, 110, 130), (2, 1) => (12, 40, 100, 110), (2, 2) => (12, 35, 110, 120),
            (3, 0) => (60, 25, 120, 140), (3, 1) => (20, 40, 110, 110), (3, 2) => (40, 35, 120, 120), (3, 3) => (30, 40, 110, 110),
            (4, 0) => (130, 10, 130, 170), (4, 1) => (90, 30, 110, 130), (4, 2) => (110, 10, 120, 170), (4, 3) => (90, 30, 110, 130),
            (5, 0) => (110, 10, 100, 90), (5, 1) => (90, 20, 110, 100), (5, 2) => (120, 10, 100, 90), (5, 3) => (140, 15, 110, 100),
            _ => (90, 30, 120, 130),
        };
    }

    protected int ZoneX() => Zone().X;
    protected int ZoneY() => Zone().Y;
    protected int ZoneW() => Zone().W;
    protected int ZoneH() => Zone().H;

    // ---------- instructions ----------
    protected static string InstrLabel(string slot) => slot switch
    {
        "attack1" => "Attack 1", "attack2" => "Attack 2", "defence1" => "Defence 1", _ => "Defence 2",
    };

    protected InstrOption InstrOf(string slot)
    {
        var name = _instr.GetValueOrDefault(slot).Name ?? "Off";
        var pool = slot.StartsWith("attack") ? AttackInstrOptions : DefenceInstrOptions;
        return pool.FirstOrDefault(o => o.Name == name) ?? pool[0];
    }

    protected int InstrPid(string slot) => _instr.GetValueOrDefault(slot).Pid;

    protected void SetInstr(string name)
    {
        var pid = InstrPid(_instrSlot);
        _instr[_instrSlot] = (name, pid);
        Game.Session?.SetInstruction(_instrSlot, $"{name}|{pid}");
    }

    protected void SetInstrPlayer(string? v)
    {
        var pid = int.TryParse(v, out var p) ? p : 0;
        var name = InstrOf(_instrSlot).Name;
        _instr[_instrSlot] = (name, pid);
        Game.Session?.SetInstruction(_instrSlot, $"{name}|{pid}");
    }

    // ---------- team tab ----------
    protected void SetDuty(string kind, string? v)
        => _duties[kind] = int.TryParse(v, out var id) ? id : null;

    protected void Recommend()
    {
        int Best(string key) => Tokens(_phase).Where(t => t.PlayerId > 0)
            .OrderByDescending(t => AbilOf(t.PlayerId).GetValueOrDefault(key)).First().PlayerId;
        _duties["cap"] = Tokens(_phase).Where(t => t.PlayerId > 0)
            .OrderByDescending(t => _ids.First(p => p.PlayerId == t.PlayerId).Age).First().PlayerId;
        _duties["fk"] = Best("set_piece_taking");
        _duties["pk"] = Best("finishing");
        _duties["ckl"] = Best("curl");
        _duties["ckr"] = Best("curl");
        _status = "Assistant assigned captain and set-piece takers.";
    }

    protected void SetAutoSub(string v)
    {
        _autoSub = v;
        Game.Session?.SetSetting($"autosub_{Game.Session.CurrentTeamId}", v);
    }

    // ---------- roles / playstyles (compiled into Player.bin by play_match) ----------
    protected sealed record RoleDef(string Name, string[] Compatible, string[] Needs);

    protected static readonly RoleDef[] RoleCatalog =
    {
        new("Goal Poacher", new[]{"CF"}, new[]{"offensive_awareness","finishing","acceleration"}),
        new("Dummy Runner", new[]{"CF","SS","AMF"}, new[]{"offensive_awareness","speed","balance"}),
        new("Fox in the Box", new[]{"CF"}, new[]{"finishing","offensive_awareness","jumping"}),
        new("Target Man", new[]{"CF"}, new[]{"heading","physical_contact","ball_control"}),
        new("Deep-Lying Forward", new[]{"CF","SS"}, new[]{"ball_control","low_pass","finishing"}),
        new("Creative Playmaker", new[]{"SS","RWF","LWF","AMF","RMF","LMF"}, new[]{"low_pass","dribbling","offensive_awareness"}),
        new("Prolific Winger", new[]{"RWF","LWF"}, new[]{"finishing","speed","dribbling"}),
        new("Roaming Flank", new[]{"RWF","LWF","RMF","LMF"}, new[]{"dribbling","speed","ball_control"}),
        new("Cross Specialist", new[]{"RWF","LWF","RMF","LMF","RB","LB"}, new[]{"lofted_pass","curl","speed"}),
        new("Classic No. 10", new[]{"SS","AMF"}, new[]{"low_pass","ball_control","tight_possession"}),
        new("Hole Player", new[]{"SS","AMF","RMF","LMF","CMF"}, new[]{"offensive_awareness","finishing","stamina"}),
        new("Box-to-Box", new[]{"RMF","LMF","CMF","DMF"}, new[]{"stamina","physical_contact","ball_control"}),
        new("Anchor Man", new[]{"DMF"}, new[]{"defensive_awareness","tackling","defensive_engagement"}),
        new("Orchestrator", new[]{"CMF","DMF"}, new[]{"low_pass","lofted_pass","offensive_awareness"}),
        new("Build Up", new[]{"CB"}, new[]{"low_pass","lofted_pass","ball_control"}),
        new("Extra Frontman", new[]{"CB"}, new[]{"heading","physical_contact","finishing"}),
        new("Attacking Full-back", new[]{"RB","LB"}, new[]{"speed","stamina","lofted_pass"}),
        new("Defensive Full-back", new[]{"RB","LB"}, new[]{"defensive_awareness","tackling","stamina"}),
        new("Full-back Finisher", new[]{"RB","LB"}, new[]{"speed","finishing","stamina"}),
        new("Offensive Goalkeeper", new[]{"GK"}, new[]{"gk_awareness","low_pass","gk_reach"}),
        new("Defensive Goalkeeper", new[]{"GK"}, new[]{"gk_reflexes","gk_catching","gk_parrying"}),
    };

    protected static readonly (string Name, string[] Compatible)[] DefCatalog =
    {
        ("The Destroyer", new[]{"CB","DMF"}),
        ("Press Back", new[]{"AMF","RMF","LMF","SS","CF","RWF","LWF"}),
        ("Front Line Pressure", new[]{"CF","SS","RWF","LWF"}),
        ("Front Line Poacher", new[]{"CF","SS"}),
        ("Attack Outlet", new[]{"CF","SS","RWF","LWF"}),
        ("All-action Defender", new[]{"CB","RB","LB"}),
        ("Pass Disruptor", new[]{"DMF","CMF"}),
        ("Covering Role", new[]{"CB","RB","LB"}),
        ("High Line Master", new[]{"CB"}),
        ("Tough Marker", new[]{"CB","RB","LB","DMF"}),
        ("Deep Defender", new[]{"CB"}),
        ("Sweeper GK", new[]{"GK"}), ("Build-up GK", new[]{"GK"}),
        ("Attacking GK", new[]{"GK"}), ("Defensive GK", new[]{"GK"}),
    };

    private readonly Dictionary<int, string> _roleOverride = new();
    private readonly Dictionary<int, string> _defStyle = new();

    protected IEnumerable<RoleDef> RolesFor(string pos)
        => RoleCatalog.Where(r => r.Compatible.Contains(pos));

    protected IEnumerable<string> DefStylesFor(string pos)
        => DefCatalog.Where(d => d.Compatible.Contains(pos)).Select(d => d.Name);

    protected void SetRole(int pid, string role)
    {
        _roleOverride[pid] = role;
        _status = $"{DetailTok(pid)?.Surname}: {role} in possession — compiles into Player.bin on the next match install.";
    }

    protected string DefStyleOf(int pid)
    {
        if (_defStyle.TryGetValue(pid, out var v)) return v;
        var (_, sec) = Db.Playstyles(pid);
        return sec is { Length: > 0 } && sec != "Basic" ? sec : "None";
    }

    protected void SetDefStyle(int pid, string name)
    {
        _defStyle[pid] = name;
        _status = $"{DetailTok(pid)?.Surname}: {(name == "None" ? "no defending style" : name)} out of possession.";
    }

    protected string FitStars(int pid, string role)
    {
        var needs = RoleCatalog.FirstOrDefault(r => r.Name == role)?.Needs;
        if (needs is null || pid == 0) return "";
        var ab = AbilOf(pid);
        if (ab.Count == 0) return "";
        var avg = needs.Select(n => ab.TryGetValue(n, out var v) ? v : 40).Average();
        return avg >= 80 ? "★★★" : avg >= 72 ? "★★" : avg >= 62 ? "★" : "☆";
    }

    // ---------- details overlay ----------
    protected string RoleOfSafe(int pid)
        => _roleOverride.TryGetValue(pid, out var o) ? o
           : Game.Session?.RoleOf(pid) is { Length: > 0 } r ? r : "Basic";

    protected IEnumerable<(string Label, int Value)> DetailAttrs(int pid, int col)
    {
        var ab = AbilOf(pid);
        var rows = AbilityCatalog.Where(a => ab.ContainsKey(a.Key))
            .Select(a => (a.Label, ab[a.Key])).ToList();
        var half = (rows.Count + 1) / 2;
        return col == 0 ? rows.Take(half) : rows.Skip(half);
    }

    protected static string ValColor(int v) => v >= 80 ? "var(--win)" : v >= 70 ? "var(--draw)" : "var(--loss)";

    protected IEnumerable<(int X, int Y)> HeatCells(int pid, string current)
    {
        var pl = _ids.FirstOrDefault(p => p.PlayerId == pid);
        var playable = new HashSet<string>(pl?.Learned ?? Array.Empty<string>()) { current };
        if (pl is not null) playable.Add(pl.Registered);
        foreach (var pos in playable)
        {
            var cell = pos switch
            {
                "GK" => (32, 102), "CB" => (32, 78), "LB" or "LWB" => (4, 78), "RB" or "RWB" => (60, 78),
                "DMF" => (32, 54), "CMF" => (32, 42), "LMF" => (4, 42), "RMF" => (60, 42),
                "AMF" => (32, 28), "LWF" => (4, 16), "RWF" => (60, 16), "SS" => (32, 16), "CF" => (32, 4),
                _ => (32, 42),
            };
            yield return cell;
        }
    }

    protected IEnumerable<string> ChangeTargets(int pid, string current)
    {
        var pl = _ids.FirstOrDefault(p => p.PlayerId == pid);
        if (pl is null) yield break;
        var opts = new HashSet<string>(pl.Learned) { pl.Registered };
        opts.Remove(current);
        foreach (var o in opts) yield return o;
    }

    protected void ChangePosition(int pid, string pos)
    {
        var slot = -1;
        for (var i = 0; i < _ids.Count; i++) if (_ids[i].PlayerId == pid) slot = i;
        if (slot < 0) return;
        var g = _geom[_phase][slot];
        _geom[_phase][slot] = (g.Adv, g.Wid, pos);
        _status = $"{_ids[slot].Surname} switches to {pos}.";
        _details = null;
        UpdateShape();
    }

    // ---------- condition / radar helpers ----------
    protected string CondClass(int pid)
        => !_cond.TryGetValue(pid, out var c) ? "good"
           : c.Injured || c.Fatigue >= 40 ? "bad" : c.Fatigue >= 20 ? "mid" : "good";

    protected string CondArrow(int pid)
        => !_cond.TryGetValue(pid, out var c) ? "▲"
           : c.Injured ? "✚" : c.Fatigue >= 40 ? "▼" : c.Fatigue >= 20 ? "►" : "▲";

    protected Dictionary<string, int> AbilOf(int pid)
    {
        if (!_abil.TryGetValue(pid, out var ab)) _abil[pid] = ab = Db.Attributes(pid);
        return ab;
    }

    protected string RadarPts(int pid)
    {
        var ab = AbilOf(pid);
        var isGk = DetailTok(pid)?.Position == "GK";
        var axes = ML.App.Visuals.RadarAxes(ab, isGk);
        return string.Join(" ", axes.Select((a, i) =>
        {
            var p = Pt(Math.Clamp(a.Value / 100.0, 0, 1), i, axes.Length);
            return $"{F(p.X)},{F(p.Y)}";
        }));
    }

    protected static (double X, double Y) Pt(double frac, int i, int n)
    {
        var a = Math.PI * 2 * i / n - Math.PI / 2;
        return (70 + 54 * frac * Math.Cos(a), 70 + 54 * frac * Math.Sin(a));
    }

    protected static string Ring(double k)
        => string.Join(" ", Enumerable.Range(0, 6).Select(i => { var p = Pt(k, i, 6); return $"{F(p.X)},{F(p.Y)}"; }));

    // ---------- save ----------
    protected void Save()
    {
        if (Game.Session is not { } s) return;
        List<(int, int, string, string, int, int)> Slots(int phase)
        {
            var list = new List<(int, int, string, string, int, int)>();
            for (var i = 0; i < _ids.Count && i < _geom[phase].Count; i++)
            {
                var g = _geom[phase][i];
                var gx = (int)Math.Round(12 + g.Wid / 100 * 80);
                var gy = (int)Math.Round(3 + g.Adv / 100 * 40);
                list.Add((i, _ids[i].PlayerId, g.Pos, RoleOfSafe(_ids[i].PlayerId),
                    Math.Clamp(gx, 12, 92), Math.Clamp(gy, 3, 43)));
            }
            return list;
        }
        var fluid = !_geom[0].SequenceEqual(_geom[1]);
        s.SaveCustomFormation(_styleIx, fluid, Slots(0), fluid ? Slots(1) : null);
        var order = _ids.Where(p => p.PlayerId > 0).Select(p => p.PlayerId)
            .Concat(_bench.Select(b => b.PlayerId)).ToList();
        s.SaveSquadOrder(order, manual: true);
        s.Captain = _duties.GetValueOrDefault("cap");
        foreach (var k in new[] { "fk", "pk", "ckl", "ckr" }) s.SetTaker(k, _duties.GetValueOrDefault(k));
        foreach (var (pid, style) in _defStyle)
        {
            if (style == "None") continue;
            Db.SetSecondaryPlaystyle(pid, style);
        }
        _status = $"Saved {_shape} ({StyleCatalog[_styleIx].Name}){(fluid ? " + defensive shape" : "")}, " +
                  "YOUR XI, positions and playstyles — the next match install writes them into dt200.";
    }

    protected static string Cat(string pos) => ML.App.Visuals.PositionCategory(pos);
    protected static string F(double d) => d.ToString("0.#", System.Globalization.CultureInfo.InvariantCulture);
}
