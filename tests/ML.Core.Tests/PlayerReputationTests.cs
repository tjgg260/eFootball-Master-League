using ML.Core.Development;
using Xunit;

namespace ML.Core.Tests;

/// <summary>
/// World reputation: what the game already knows about a man before your club has watched him.
///
/// <para>
/// The fixtures are real rows from the world database rather than invented numbers, because the
/// whole model is calibrated against that population and a made-up superstar would not exercise
/// it. Kylian Mbappé is player 700231747 (overall 93, free agent — no market row at all, which
/// is exactly the case the old proximity-only model scored as "nobody has watched him").
/// </para>
/// </summary>
public class PlayerReputationTests
{
    private const long MbappeId = 700231747;

    /// <summary>His 21 outfield abilities, verbatim.</summary>
    private static Dictionary<string, int> Mbappe() => new()
    {
        ["speed"] = 97, ["acceleration"] = 97, ["tight_possession"] = 93, ["ball_control"] = 93,
        ["dribbling"] = 93, ["finishing"] = 92, ["stamina"] = 92, ["offensive_awareness"] = 91,
        ["kicking_power"] = 90, ["low_pass"] = 85, ["balance"] = 82, ["curl"] = 80,
        ["physical_contact"] = 77, ["jumping"] = 77, ["lofted_pass"] = 74, ["heading"] = 72,
        ["set_piece_taking"] = 69, ["tackling"] = 40, ["defensive_awareness"] = 40,
        ["aggression"] = 40, ["defensive_engagement"] = 40,
    };

    /// <summary>A fourth-division journeyman: nothing outstanding, nothing terrible.</summary>
    private static Dictionary<string, int> Journeyman() => new()
    {
        ["speed"] = 58, ["acceleration"] = 59, ["tight_possession"] = 55, ["ball_control"] = 54,
        ["dribbling"] = 52, ["finishing"] = 49, ["stamina"] = 57, ["offensive_awareness"] = 53,
        ["kicking_power"] = 50, ["low_pass"] = 54, ["balance"] = 55, ["curl"] = 48,
        ["physical_contact"] = 56, ["jumping"] = 54, ["lofted_pass"] = 52, ["heading"] = 51,
        ["set_piece_taking"] = 45, ["tackling"] = 53, ["defensive_awareness"] = 52,
        ["aggression"] = 57, ["defensive_engagement"] = 56,
    };

    // ─────────────────────────────────────────────────────────── the score

    [Fact]
    public void Ability_claim_is_linear_between_the_measured_rarity_anchors()
    {
        // 66 is the top 8.4% of the world and buys nothing; 90 is the top 0.0011%.
        Assert.Equal(0.0, PlayerReputation.AbilityClaim(66), 3);
        Assert.Equal(0.0, PlayerReputation.AbilityClaim(40), 3);
        Assert.Equal(50.0, PlayerReputation.AbilityClaim(78), 3);
        Assert.Equal(100.0, PlayerReputation.AbilityClaim(90), 3);
        // Two rows in the world carry a 116. The guard keeps them at 100, not 208.
        Assert.Equal(100.0, PlayerReputation.AbilityClaim(116), 3);
    }

    [Fact]
    public void Price_claim_follows_the_two_log_segments()
    {
        // Anchored so that a given claim means the same RARITY whether it was earned by ability
        // or by transfer fee: £10M and an overall of 76 are about equally rare, and both score
        // in the low 40s. A null or worthless value is an ABSENT signal, not a claim of zero.
        Assert.Equal(0.0, PlayerReputation.PriceClaim(null), 6);
        Assert.Equal(0.0, PlayerReputation.PriceClaim(0), 6);
        Assert.Equal(0.0, PlayerReputation.PriceClaim(250_000), 6);
        Assert.Equal(10.0, PlayerReputation.PriceClaim(1_000_000), 6);
        Assert.InRange(PlayerReputation.PriceClaim(10_000_000), 40.0, 41.0);
        Assert.InRange(PlayerReputation.PriceClaim(50_000_000), 61.5, 62.5);
        Assert.InRange(PlayerReputation.PriceClaim(120_000_000), 81.0, 82.0);
        Assert.InRange(PlayerReputation.PriceClaim(180_000_000), 91.5, 92.5);
        Assert.InRange(PlayerReputation.PriceClaim(240_000_000), 98.5, 100.0);
        // Monotonic across the knee, so a £1 rise never costs a player fame.
        var previous = -1.0;
        for (var v = 100_000L; v < 300_000_000L; v = (long)(v * 1.05))
        {
            var claim = PlayerReputation.PriceClaim(v);
            Assert.True(claim >= previous, $"£{v} scored {claim} after {previous}");
            previous = claim;
        }
    }

    [Fact]
    public void Caps_claim_stops_at_seventy_five_so_a_small_nations_veteran_is_not_Mbappe()
    {
        Assert.Equal(0.0, PlayerReputation.CapsClaim(null), 6);
        Assert.Equal(0.0, PlayerReputation.CapsClaim(4), 6);
        Assert.Equal(0.0, PlayerReputation.CapsClaim(5), 6);
        Assert.InRange(PlayerReputation.CapsClaim(10), 16.5, 17.5);
        Assert.Equal(56.0, PlayerReputation.CapsClaim(50), 6);
        Assert.InRange(PlayerReputation.CapsClaim(100), 72.5, 73.5);
        Assert.Equal(75.0, PlayerReputation.CapsClaim(150), 6);
        Assert.Equal(75.0, PlayerReputation.CapsClaim(400), 6);
    }

    [Fact]
    public void Stage_claim_scales_the_club_by_how_central_he_is_to_it()
    {
        // Real Madrid (9,150) — a star there is as known as the stage can make you, and that
        // is 55, not 100. Playing for a giant does not make you the best player in the world.
        Assert.Equal(55.0, PlayerReputation.StageClaim(9150, "Star Player"), 1);
        Assert.True(PlayerReputation.StageClaim(9150, "Backup")
                    < PlayerReputation.StageClaim(9150, "Regular Starter"));
        Assert.True(PlayerReputation.StageClaim(9150, "Regular Starter")
                    < PlayerReputation.StageClaim(9150, "Star Player"));
        // League Two (4,200) is the zero point: its star is invisible to the wider game.
        Assert.InRange(PlayerReputation.StageClaim(4200, "Star Player"), 0.0, 3.0);
        // An unrecognised or absent status is NEUTRAL, never punished for a vocabulary gap.
        Assert.Equal(0.60, PlayerReputation.RoleWeight(null), 3);
        Assert.Equal(0.60, PlayerReputation.RoleWeight("Talismanic Colossus"), 3);
    }

    [Fact]
    public void A_missing_signal_can_never_make_a_player_less_famous()
    {
        // The free-agent Mbappé record: no market row, no caps column, no club at all. Under a
        // mean he would be dragged to nothing; under max() his rating alone still says who he is.
        var barest = new ReputationInputs(93, null, null, null, null);
        Assert.Equal(100, PlayerReputation.Score(barest));

        // Adding signals can only ever raise him.
        var fuller = barest with { MarketValue = 175_000_000, InternationalCaps = 70 };
        Assert.True(PlayerReputation.Score(fuller) >= PlayerReputation.Score(barest));

        // A blank market value is UNKNOWN, not worthless: it must not beat the ability claim.
        var priced = new ReputationInputs(93, 250_000, null, null, null);
        Assert.Equal(100, PlayerReputation.Score(priced));
    }

    [Fact]
    public void Caps_keep_an_ageing_great_famous_after_his_value_collapses()
    {
        // Messi in this world: overall 82, £14M, 175 caps, Inter Miami (6,650), star player.
        var messi = new ReputationInputs(82, 14_000_000, 175, 6650, "Star Player");
        Assert.Equal(75, PlayerReputation.Score(messi));
        // Strike the caps out and the same man drops to a good-but-ordinary 67. That gap IS the
        // channel: the world does not forget a man because his transfer fee did.
        Assert.Equal(67, PlayerReputation.Score(messi with { InternationalCaps = null }));
    }

    [Fact]
    public void The_stage_alone_can_make_an_ordinary_rating_known()
    {
        // Overall 60 is the world median and claims nothing; a starting place at a giant does.
        var squadFiller = new ReputationInputs(60, null, null, 9400, "Star Player");
        Assert.Equal(0.0, PlayerReputation.AbilityClaim(60), 3);
        Assert.Equal(55, PlayerReputation.Score(squadFiller));
    }

    [Fact]
    public void A_nobody_scores_nothing()
    {
        Assert.Equal(0, PlayerReputation.Score(new ReputationInputs(58, null, null, null, null)));
        Assert.Equal(0, PlayerReputation.Score(new ReputationInputs(58, 0, 0, 0, null)));
        // A youngster at a mid-table club is a name to nobody outside it.
        Assert.Equal(0, PlayerReputation.Score(new ReputationInputs(55, 20_000, 0, 3400, "Youngster")));
    }

    // ─────────────────────────────────────────────────────────── fame as a knowledge floor

    [Fact]
    public void Strictness_orders_the_knowledge_floor_and_never_inverts()
    {
        for (var rep = 0; rep <= 100; rep++)
        {
            var relaxed = PlayerReputation.KnowledgeFloor(rep, MaskingStrictness.Relaxed);
            var standard = PlayerReputation.KnowledgeFloor(rep, MaskingStrictness.Standard);
            var strict = PlayerReputation.KnowledgeFloor(rep, MaskingStrictness.Strict);
            Assert.True(relaxed >= standard, $"rep {rep}: relaxed {relaxed} < standard {standard}");
            Assert.True(standard >= strict, $"rep {rep}: standard {standard} < strict {strict}");
        }
        // The setting has to MEAN something at the top of the scale, not merely not invert.
        Assert.Equal(60, PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Relaxed));
        Assert.Equal(45, PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Standard));
        Assert.Equal(30, PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Strict));
    }

    [Fact]
    public void The_knowledge_floor_rises_with_fame_and_is_nothing_without_it()
    {
        Assert.Equal(0, PlayerReputation.KnowledgeFloor(0, MaskingStrictness.Standard));
        Assert.Equal(0, PlayerReputation.KnowledgeFloor(-5, MaskingStrictness.Relaxed));
        var last = -1;
        for (var rep = 0; rep <= 100; rep++)
        {
            var floor = PlayerReputation.KnowledgeFloor(rep, MaskingStrictness.Standard);
            Assert.True(floor >= last, "the floor must never fall as fame rises");
            last = floor;
        }
    }

    [Fact]
    public void Fame_never_buys_the_scouted_half_of_a_dossier()
    {
        // The app opens character, ceiling and traits at 45 and gates them on SCOUTED knowledge.
        // Even so, the fame floor never EXCEEDS that line on Standard, and only the handful of
        // men who score 99 or 100 in the whole world so much as reach it.
        Assert.True(PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Standard) <= 45);
        Assert.True(PlayerReputation.KnowledgeFloor(95, MaskingStrictness.Standard) < 45);
        Assert.True(PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Strict) < 45);
    }

    // ─────────────────────────────────────────────────────────── the reveal order

    [Fact]
    public void Everyone_knows_Mbappe_is_rapid_and_can_finish()
    {
        var order = RevealOrder.For(MbappeId, Mbappe(), isGk: false, reputation: 100);
        var floor = PlayerReputation.KnowledgeFloor(100, MaskingStrictness.Standard);   // 45

        // The headline, free, without a scout ever leaving the building.
        Assert.True(order.IsRevealed("speed", floor));
        Assert.True(order.IsRevealed("acceleration", floor));
        Assert.True(order.IsRevealed("finishing", floor));

        // And what he is NOT famous for stays dark. Every one of his four 40s is hidden.
        Assert.False(order.IsRevealed("tackling", floor));
        Assert.False(order.IsRevealed("defensive_awareness", floor));
        Assert.False(order.IsRevealed("aggression", floor));
        Assert.False(order.IsRevealed("defensive_engagement", floor));
    }

    [Fact]
    public void Reputation_changes_which_abilities_you_see_not_how_many()
    {
        var abilities = Mbappe();
        var famous = RevealOrder.For(MbappeId, abilities, false, reputation: 100);
        var blind = RevealOrder.For(MbappeId, abilities, false, reputation: 0);

        var seenFamous = abilities.Keys.Count(a => famous.IsRevealed(a, 45));
        var seenBlind = abilities.Keys.Count(a => blind.IsRevealed(a, 45));

        // 9 against 7 of 21: fame is a reordering, not a discount. It must not become a
        // cheaper scout.
        Assert.Equal(9, seenFamous);
        Assert.Equal(7, seenBlind);

        // The unbiased order is the absurdity being fixed — it hides his pace and his finishing
        // and volunteers one of his 40s instead.
        Assert.False(blind.IsRevealed("speed", 45));
        Assert.False(blind.IsRevealed("finishing", 45));
        Assert.True(blind.IsRevealed("defensive_awareness", 45));
    }

    [Fact]
    public void Scouting_a_famous_player_is_still_worth_doing()
    {
        var abilities = Mbappe();
        var order = RevealOrder.For(MbappeId, abilities, false, reputation: 100);

        // What reputation alone hands you, and what each further step of scouting adds.
        Assert.Equal(9, abilities.Keys.Count(a => order.IsRevealed(a, 45)));
        Assert.Equal(16, abilities.Keys.Count(a => order.IsRevealed(a, 75)));
        Assert.Equal(21, abilities.Keys.Count(a => order.IsRevealed(a, 100)));

        // More than half of him is still unknown at the fame floor, and all of the half worth
        // knowing if you have to play against him.
        var hidden = abilities.Keys.Where(a => !order.IsRevealed(a, 45)).ToList();
        Assert.Equal(12, hidden.Count);
        Assert.All(abilities.Where(a => a.Value < 50).Select(a => a.Key),
                   weak => Assert.Contains(weak, hidden));
    }

    [Fact]
    public void The_coach_praises_a_famous_man_for_free_and_finds_his_flaws_only_by_watching()
    {
        var abilities = Mbappe();
        var order = RevealOrder.For(MbappeId, abilities, false, reputation: 100);

        var onReputation = AttributeKnowledge.CoachReport(MbappeId, abilities, false, 45, order);
        Assert.Contains("Exceptional pace", onReputation);
        Assert.DoesNotContain(onReputation, line => line.StartsWith("Poor "));

        var scouted = AttributeKnowledge.CoachReport(MbappeId, abilities, false, 100, order);
        Assert.Contains("Exceptional pace", scouted);
        Assert.Contains(scouted, line => line.StartsWith("Poor "));
    }

    [Fact]
    public void A_nobody_reveals_nothing()
    {
        var abilities = Journeyman();
        var reputation = PlayerReputation.Score(new ReputationInputs(58, 20_000, 0, 3400, "Squad Player"));
        Assert.Equal(0, reputation);

        var knowledge = PlayerReputation.KnowledgeFloor(reputation, MaskingStrictness.Standard);
        Assert.Equal(0, knowledge);

        var order = RevealOrder.For(4242, abilities, false, reputation);
        Assert.All(abilities.Keys, a => Assert.False(order.IsRevealed(a, knowledge)));
        Assert.Empty(order.Headline(knowledge));
        Assert.Empty(AttributeKnowledge.CoachReport(4242, abilities, false, knowledge, order));
    }

    [Fact]
    public void Full_knowledge_reveals_everything_however_famous_he_is()
    {
        var abilities = Mbappe();
        foreach (var reputation in new[] { 0, 37, 100 })
        {
            var order = RevealOrder.For(MbappeId, abilities, false, reputation);
            Assert.All(abilities.Keys, a => Assert.True(order.IsRevealed(a, 100)));
            // Including keys outside his family, which fame says nothing about either way.
            Assert.True(order.IsRevealed("gk_reflexes", 100));
            Assert.True(order.IsRevealed("foot", 100));
            // And nothing at all at zero.
            Assert.All(abilities.Keys, a => Assert.False(order.IsRevealed(a, 0)));
        }
    }

    [Fact]
    public void Reveal_is_deterministic_and_monotonic_at_every_fame_level()
    {
        var abilities = Mbappe();
        // Two dictionaries with different insertion order must rank identically — the tie-break
        // is ordinal on the key, never enumeration order.
        var forwards = new Dictionary<string, int>(abilities);
        var backwards = new Dictionary<string, int>();
        foreach (var kv in abilities.Reverse()) backwards[kv.Key] = kv.Value;

        foreach (var reputation in new[] { 0, 25, 60, 100 })
        {
            var a = RevealOrder.For(MbappeId, forwards, false, reputation);
            var b = RevealOrder.For(MbappeId, backwards, false, reputation);
            foreach (var attr in abilities.Keys)
            {
                for (var k = 0; k <= 100; k += 5)
                {
                    Assert.Equal(a.IsRevealed(attr, k), b.IsRevealed(attr, k));
                    // More knowledge never HIDES an ability.
                    if (a.IsRevealed(attr, k)) Assert.True(a.IsRevealed(attr, k + 5));
                }
            }
        }
    }

    [Fact]
    public void At_zero_fame_the_order_is_exactly_the_old_unbiased_hash()
    {
        // The 87% of the world nobody has heard of must render precisely as they did before
        // reputation existed.
        var abilities = Mbappe();
        var order = RevealOrder.For(MbappeId, abilities, false, reputation: 0);
        foreach (var attr in abilities.Keys)
        {
            for (var k = 0; k <= 100; k += 10)
            {
                Assert.Equal(AttributeKnowledge.IsRevealed(MbappeId, attr, k),
                             order.IsRevealed(attr, k));
            }
        }
    }

    [Fact]
    public void A_keeper_is_judged_as_a_keeper()
    {
        // Ter Stegen: elite hands, ordinary feet, no pace.
        var keeper = new Dictionary<string, int>
        {
            ["gk_reach"] = 92, ["gk_awareness"] = 92, ["gk_catching"] = 92, ["gk_parrying"] = 92,
            ["gk_reflexes"] = 92, ["physical_contact"] = 80, ["jumping"] = 80,
            ["kicking_power"] = 69, ["lofted_pass"] = 65, ["low_pass"] = 63, ["speed"] = 52,
            ["ball_control"] = 40, ["balance"] = 45, ["acceleration"] = 47,
            // Attributes no keeper's reputation is built on — they must stay out of the ranking.
            ["tackling"] = 41, ["finishing"] = 40, ["stamina"] = 46,
        };
        var order = RevealOrder.For(999, keeper, isGk: true, reputation: 100);

        Assert.True(order.IsRevealed("gk_reach", 45));
        Assert.True(order.IsRevealed("gk_reflexes", 45));
        Assert.False(order.IsRevealed("ball_control", 45));
        Assert.False(order.IsRevealed("acceleration", 45));

        var headline = order.Headline(45, 3);
        Assert.All(headline, a => Assert.StartsWith("gk_", a));
    }

    [Fact]
    public void The_headline_is_what_he_is_famous_for_best_first()
    {
        var order = RevealOrder.For(MbappeId, Mbappe(), false, reputation: 100);
        var headline = order.Headline(45, 2);
        Assert.Equal(new[] { "speed", "acceleration" }, headline);
        Assert.Equal("pace", AttributeKnowledge.Noun(headline[0]));
        // Nothing is headline material at zero knowledge, however famous he is.
        Assert.Empty(order.Headline(0, 2));
    }

    [Fact]
    public void The_population_tables_cover_exactly_the_apps_ability_keys()
    {
        var abilities = AttributeKnowledge.AbilityKeys.ToHashSet();
        Assert.Equal(26, abilities.Count);

        var outfield = PlayerReputation.Population(isGk: false);
        Assert.Equal(21, outfield.Count);
        Assert.All(outfield.Keys, k => Assert.Contains(k, abilities));
        Assert.DoesNotContain(outfield.Keys, k => k.StartsWith("gk_"));

        var keeper = PlayerReputation.Population(isGk: true);
        Assert.All(keeper.Keys, k => Assert.Contains(k, abilities));
        Assert.Equal(5, keeper.Keys.Count(k => k.StartsWith("gk_")));

        // Every spread is real, so no z-score can divide by nothing.
        Assert.All(outfield.Values, p => Assert.True(p.Sd > 1.0));
        Assert.All(keeper.Values, p => Assert.True(p.Sd > 1.0));
    }
}
