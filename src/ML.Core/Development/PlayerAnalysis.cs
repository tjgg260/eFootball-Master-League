namespace ML.Core.Development;

/// <summary>
/// The MFL-style qualitative read of a player: six analysis panels (Attacking / Skills /
/// Movement / Power / Mentality / Defending — goalkeeping variants for keepers), each a set of
/// graded STATEMENTS derived from his abilities. This is the north star's core feature: the app
/// never shows the number, it shows "A solid and consistent finishing ability  B" with a tone.
/// Pure maths/wording; knowledge gating uses the same monotonic reveal as the attribute masking.
/// </summary>
public static class PlayerAnalysis
{
    public enum Tone { Good, Mid, Poor }

    public sealed record Line(string Text, string Grade, Tone Tone);

    public sealed record Panel(string Name, IReadOnlyList<Line> Lines);

    // statement: attribute(s) averaged -> band phrasing (>=78 / >=64 / >=52 / below)
    private sealed record Stmt(string[] Attrs, string High, string Solid, string Modest, string Poor);

    private static readonly (string Panel, Stmt[] Stmts)[] Outfield =
    {
        ("Attacking Analysis", new[]
        {
            new Stmt(new[]{"curl","lofted_pass"}, "Whips in wicked, precise crosses",
                "Reasonably accurate crossing technique", "Crossing is serviceable at best",
                "Crossing lacks any real quality"),
            new Stmt(new[]{"finishing"}, "A clinical finisher from almost anywhere",
                "A solid and consistent finishing ability", "Takes his chances adequately",
                "Wasteful in front of goal"),
            new Stmt(new[]{"heading"}, "Commanding and precise with his head",
                "A reliable aerial threat in the box", "Heading is passable",
                "Heading lacks precision and direction"),
            new Stmt(new[]{"low_pass"}, "Slices defences open with his passing",
                "Keeps the ball moving with simple passes", "Passing is safe but limited",
                "Struggles to find a team-mate"),
            new Stmt(new[]{"finishing","balance"}, "Strikes volleys as cleanly as set balls",
                "Capable when the ball drops to him", "Inconsistent volleying ability",
                "Panics when the ball arrives in the air"),
        }),
        ("Skills Analysis", new[]
        {
            new Stmt(new[]{"dribbling"}, "Regularly beats defenders with the ball",
                "Comfortable taking his man on", "Occasionally wriggles past a defender",
                "Rarely beats the first man"),
            new Stmt(new[]{"set_piece_taking"}, "A genuine set-piece specialist",
                "Dangerous delivery from set-pieces", "Decent placement, but lacks threat",
                "Set-pieces are a wasted possession"),
            new Stmt(new[]{"lofted_pass"}, "Switches play with raking long balls",
                "Finds team-mates with longer passing", "Lacks precision on long balls",
                "Long passing is a liability"),
            new Stmt(new[]{"ball_control"}, "The ball obeys him instantly",
                "Displays consistent ball control", "First touch can let him down",
                "Heavy first touch invites trouble"),
            new Stmt(new[]{"tight_possession"}, "Impossible to dispossess in tight spaces",
                "Keeps the ball under pressure", "Loses it when crowded",
                "Coughs up possession under any pressure"),
        }),
        ("Movement Analysis", new[]
        {
            new Stmt(new[]{"acceleration"}, "Devastating over the first five yards",
                "Sharp, responsive acceleration", "Takes a while to reach top speed",
                "Ponderous from a standing start"),
            new Stmt(new[]{"speed"}, "Blistering pace in full flight",
                "Hard to catch when in full stride", "Not blessed with real pace",
                "One of the slowest on the pitch"),
            new Stmt(new[]{"balance"}, "Glides across the turf, never off balance",
                "Moves fluidly on and off the ball", "Can be knocked off his stride",
                "Easily bundled off the ball"),
            new Stmt(new[]{"offensive_awareness","acceleration"}, "Reads the game a beat before everyone",
                "Quick to adapt and react to the ball", "Reactions are ordinary",
                "Always a step behind the play"),
        }),
        ("Power Analysis", new[]
        {
            new Stmt(new[]{"kicking_power"}, "Ferocious power in either boot",
                "Strikes the ball with authority", "Shot power is unremarkable",
                "Shots rarely trouble a keeper"),
            new Stmt(new[]{"jumping"}, "Owns the airspace in both boxes",
                "Reasonably effective in the air", "Second-best in most aerial duels",
                "A bystander in the air"),
            new Stmt(new[]{"stamina"}, "Runs the full 90 twice over",
                "Covers large distances for the full 90", "Fades in the final quarter",
                "Out on his feet by the hour mark"),
            new Stmt(new[]{"physical_contact"}, "A physical mismatch for anyone",
                "Can hold his ground in challenges", "Comes off worse in physical duels",
                "Brushed aside far too easily"),
            new Stmt(new[]{"kicking_power","finishing"}, "A constant threat from distance",
                "A reliable shooting threat from distance", "Long-range efforts are speculative",
                "Shooting from range is a turnover"),
        }),
        ("Mentality Analysis", new[]
        {
            new Stmt(new[]{"aggression"}, "Ferocious commitment in every duel",
                "Fully committed in the tackle", "Picks his battles carefully",
                "Lacks commitment in the tackle"),
            new Stmt(new[]{"defensive_awareness"}, "Snuffs out danger before it forms",
                "Reads play to intercept passes", "Interceptions are occasional",
                "Rarely reads play to intercept passes"),
            new Stmt(new[]{"offensive_awareness"}, "Finds space that shouldn't exist",
                "Good awareness to find pockets of space", "Movement off the ball is routine",
                "Static without the ball"),
            new Stmt(new[]{"low_pass","offensive_awareness"}, "Sees passing lanes others can't",
                "Recognizes open passing lanes", "Passing choices are conservative",
                "Blind to the killer pass"),
            new Stmt(new[]{"set_piece_taking","balance"}, "Ice-cold from the penalty spot",
                "Dependable enough from the spot", "Penalty taking cracks under pressure",
                "A liability from twelve yards"),
            new Stmt(new[]{"balance","ball_control"}, "Utterly composed in the box",
                "Composed in attacking situations", "Hurried when the chance arrives",
                "Snatches at the big moments"),
        }),
        ("Defending Analysis", new[]
        {
            new Stmt(new[]{"defensive_awareness"}, "Always in exactly the right place",
                "Positionally sound and alert", "Occasionally caught out of position",
                "A liability; often out of position"),
            new Stmt(new[]{"tackling"}, "Times challenges to perfection",
                "Wins his tackles cleanly", "Tackling is hit and miss",
                "Often mistimed and clumsy"),
            new Stmt(new[]{"tackling","aggression"}, "Slide tackles are last-ditch art",
                "Uses the slide tackle well", "Sliding challenges are a gamble",
                "Mistimed and risky sliding tackles"),
            new Stmt(new[]{"defensive_engagement"}, "Presses like his life depends on it",
                "Presses opponents with real intent", "Pressing is half-hearted",
                "Stands off and watches"),
        }),
    };

    private static readonly (string Panel, Stmt[] Stmts)[] Keeper =
    {
        ("Shot-Stopping Analysis", new[]
        {
            new Stmt(new[]{"gk_reflexes"}, "Reflexes that defy belief",
                "Sharp reflexes on the line", "Reflex saves are ordinary",
                "Slow to react on the line"),
            new Stmt(new[]{"gk_parrying"}, "Turns everything round the post",
                "Parries danger to safe areas", "Parries can drop dangerously",
                "Spills shots into the six-yard box"),
            new Stmt(new[]{"gk_reach"}, "Covers every inch of the goal",
                "Good reach across the goal", "Beaten by well-placed efforts",
                "The corners are unguarded"),
        }),
        ("Command Analysis", new[]
        {
            new Stmt(new[]{"gk_awareness"}, "Commands his area like a general",
                "Decent command of his area", "Hesitant coming for crosses",
                "A stranger to his own six-yard box"),
            new Stmt(new[]{"gk_catching"}, "Catches everything, gives nothing back",
                "Safe, reliable handling", "Prefers to punch under pressure",
                "Handling is an adventure"),
        }),
        ("Distribution Analysis", new[]
        {
            new Stmt(new[]{"low_pass"}, "Starts attacks like a deep playmaker",
                "Comfortable playing out short", "Short distribution is safe at best",
                "Panics with the ball at his feet"),
            new Stmt(new[]{"lofted_pass","kicking_power"}, "Launches precise counters at will",
                "Finds targets with longer kicks", "Long kicking lacks accuracy",
                "Distribution surrenders possession"),
        }),
        ("Movement Analysis", new[]
        {
            new Stmt(new[]{"acceleration","speed"}, "Off his line in a flash",
                "Quick off his line", "Slow to leave his line",
                "Rooted to the goal line"),
            new Stmt(new[]{"balance"}, "Recovers position instantly",
                "Solid footwork around the goal", "Footwork can get tangled",
                "Clumsy repositioning"),
        }),
        ("Power Analysis", new[]
        {
            new Stmt(new[]{"jumping"}, "Claims the highest ball in the stadium",
                "Reasonably dominant in the air", "Out-jumped at crosses",
                "Loses the aerial battle in his own box"),
            new Stmt(new[]{"physical_contact"}, "Immovable under pressure",
                "Stands firm in a crowded box", "Bullied at set-pieces",
                "Muscled off every high ball"),
            new Stmt(new[]{"stamina"}, "Concentration never dips",
                "Reliable for the full match", "Focus drifts late on",
                "Mistakes creep in as legs tire"),
        }),
    };

    /// <summary>Build the graded panels. Statements whose attributes aren't revealed at this
    /// knowledge level are omitted — an unscouted player shows a thin, honest dossier.</summary>
    public static IReadOnlyList<Panel> Build(
        long playerId, IReadOnlyDictionary<string, int> abilities, bool isGk, int knowledge,
        RevealOrder? order = null)
    {
        var catalog = isGk ? Keeper : Outfield;
        var panels = new List<Panel>();
        foreach (var (name, stmts) in catalog)
        {
            var lines = new List<Line>();
            foreach (var s in stmts)
            {
                var vals = s.Attrs.Where(abilities.ContainsKey)
                    .Where(a => AttributeKnowledge.IsRevealed(playerId, a, knowledge, order))
                    .Select(a => abilities[a]).ToList();
                if (vals.Count < s.Attrs.Length)
                    continue;                        // not fully revealed -> not stated
                var v = (int)Math.Round(vals.Average());
                var text = v >= 78 ? s.High : v >= 64 ? s.Solid : v >= 52 ? s.Modest : s.Poor;
                var tone = v >= 70 ? Tone.Good : v >= 58 ? Tone.Mid : Tone.Poor;
                lines.Add(new Line(text, AttributeKnowledge.Grade(v), tone));
            }
            if (lines.Count > 0)
                panels.Add(new Panel(name, lines));
        }
        return panels;
    }
}
