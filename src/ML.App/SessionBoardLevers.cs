using ML.Core.Management;

namespace ML.App;

/// <summary>
/// Board levers (build item 4): ask the chairman for money, invest in the training ground and
/// the academy, and give every AI dugout a real name from Konami's coach pool (Coach.bin →
/// `coach_names`, 906 names). Facility levels feed development and intake quality.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ board confidence

    /// <summary>
    /// Every confidence swing the per-result gauge knows nothing about: the season verdict, the
    /// mid-season review, a budget ask turned down.
    ///
    /// THE BUG: all of those used to write straight into `board_conf` and stop there, and that
    /// was two failures in one. First, the live <see cref="Board"/> object is built ONCE in the
    /// Session constructor, seeded from `board_conf`, and never re-read — so a season in which
    /// you hit every objective (+8 apiece) left every gauge in the app reading exactly what it
    /// read the day before. Second, ApplyCareerAfterResult writes the live object's value back
    /// over `board_conf` after every league result, so those swings were not merely invisible,
    /// they were erased at the next kick-off.
    ///
    /// Keeping them in a key nothing else writes, and adding them back on every read, makes the
    /// number that is stored and the number you are shown the same number again. Keyed per club
    /// so a new job (which resets `board_conf`) starts from a clean slate, exactly like the fan
    /// ledger next door in SessionObjectives.
    /// </summary>
    private int BoardSwing
    {
        get => int.TryParse(GetMeta($"board_swing_{CurrentTeamId}"), out var v) ? v : 0;
        set => SetMeta($"board_swing_{CurrentTeamId}", value.ToString());
    }

    /// <summary>Board confidence as it stands RIGHT NOW — re-read from store, never cached.</summary>
    public int BoardConfidenceNow =>
        Math.Clamp(StoredBoardConfidence + BoardSwing, BoardConfidence.Min, BoardConfidence.Max);

    /// <summary>
    /// The whole board gauge — value, label, under-threat — rebuilt from the stored numbers on
    /// every read. <see cref="Board"/> still owns the expectation and the per-result maths; this
    /// is what a screen or a rule should ASK, because it cannot go stale between two reads.
    /// </summary>
    public BoardConfidence BoardNow => new(Board.Expectation, BoardConfidenceNow);

    /// <summary>
    /// Move board confidence and keep the visible number clamped to 0-100. The swing is stored
    /// as the difference from the result-driven value, so the per-result gauge can keep writing
    /// `board_conf` underneath us without ever eating a verdict.
    /// </summary>
    public void MoveBoardConfidence(int delta)
    {
        var target = Math.Clamp(BoardConfidenceNow + delta,
            BoardConfidence.Min, BoardConfidence.Max);
        BoardSwing = target - StoredBoardConfidence;
    }

    // ------------------------------------------------------------------ debt (B5)

    /// <summary>
    /// B5: running a deficit used to cost nothing — SyncBudget floored the persisted balance at
    /// £0, so debt didn't even survive a reload, let alone matter. Now that it does survive
    /// (SessionWorld.SyncBudget), it needs a consequence: every week you stay in the red costs a
    /// small board-confidence hit — the same lever a bad result or a missed objective moves — and
    /// the FIRST week you go into the red gets a named inbox warning so the drift doesn't arrive
    /// as a mystery. This is not a bankruptcy model (no forced sales, no relegation-by-administration);
    /// it is what actually enforces the debt: the same sack risk a struggling season already
    /// carries just picks up an extra source of pressure.
    /// </summary>
    private void ApplyDebtPressure(int matchday)
    {
        var key = $"debt_warned_{CurrentTeamId}";
        var wasWarned = GetMeta(key) == "1";
        if (!Finances.InTheRed)
        {
            if (wasWarned) SetMeta(key, "0");
            return;
        }
        MoveBoardConfidence(-1);
        if (!wasWarned)
        {
            SetMeta(key, "1");
            PostInbox("Club", "The club is in the red",
                $"The balance has slipped to £{Finances.Balance:N0}. The board notices every week " +
                "it stays that way — clear it before it costs you their patience.", matchday);
        }
    }

    // ------------------------------------------------------------------ AI manager names

    /// <summary>Real coach name for any club's dugout; yours is your own.</summary>
    public string ManagerNameOf(int teamId)
    {
        if (teamId == CurrentTeamId) return ManagerName;
        // B7: the club's own assigned Assistant Manager (AssignStartingStaff) beats the old
        // coach_names guess — coach_names is a table the MVP world builder never fills, so this
        // fallback used to print "the manager" for all 351 other dugouts, every time.
        if (AssistantManagerNameOf(teamId) is { Length: > 0 } real) return real;
        if (GetMeta($"mgrname_{teamId}") is { Length: > 0 } stored) return stored;
        var name = PickCoachName(teamId);
        SetMeta($"mgrname_{teamId}", name);
        return name;
    }

    private string? AssistantManagerNameOf(int teamId)
    {
        EnsureStaffPool();
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT name FROM staff_people WHERE team_id=$t AND role='Assistant Manager' LIMIT 1";
        cmd.Parameters.AddWithValue("$t", teamId);
        return cmd.ExecuteScalar() as string;
    }

    private string PickCoachName(int teamId)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM coach_names";
        int count;
        try { count = Convert.ToInt32(cmd.ExecuteScalar()); }
        catch { return "the manager"; }
        if (count == 0) return "the manager";
        var pick = (int)((uint)((teamId * 2654435761) ^ WorldSeed) % count);
        using var sel = Db.Connection.CreateCommand();
        sel.CommandText = "SELECT name FROM coach_names ORDER BY name LIMIT 1 OFFSET $o";
        sel.Parameters.AddWithValue("$o", pick);
        return sel.ExecuteScalar() as string ?? "the manager";
    }

    /// <summary>Your own name — set it in Settings; defaults to "The Gaffer".</summary>
    public string ManagerName
    {
        get => GetMeta("manager_name") is { Length: > 0 } v ? v : "The Gaffer";
        set => SetMeta("manager_name", value.Trim());
    }

    // ------------------------------------------------------------------ budget request

    /// <summary>Ask the board for extra transfer money. One ask per season; they remember.</summary>
    public string RequestBudget()
    {
        if (GetMeta($"budgetask_{SeasonId}") is not null)
            return "You already went to the board this season — twice would be pushing it.";
        SetMeta($"budgetask_{SeasonId}", "1");
        // Ask the live number, not the constructor's copy of it: a verdict or a review earlier
        // this session moves what the board is willing to sign off on.
        var confidence = BoardConfidenceNow;
        if (confidence < 55)
        {
            MoveBoardConfidence(-2);
            PostInbox("Board", "Budget request declined",
                $"Chairman {Chairman()} is unmoved: \"Results first, money after.\"");
            return "Declined — the board wants results before it writes cheques.";
        }
        // Backing scales with how much they believe in you.
        var grant = 500_000L * (1 + (confidence - 55) / 10);
        Finances.ReceivePrize(grant);
        AdjustBudget(grant);
        PostInbox("Board", "The board finds extra money",
            $"Chairman {Chairman()} frees up £{grant:N0} for the transfer kitty. Spend it well.");
        return $"Granted — £{grant:N0} added to the budget.";
    }

    // ------------------------------------------------------------------ facilities

    public int TrainingLevel
    {
        get => int.TryParse(GetMeta($"trainlvl_{CurrentTeamId}"), out var v) ? Math.Clamp(v, 1, 5) : 1;
        private set => SetMeta($"trainlvl_{CurrentTeamId}", value.ToString());
    }

    public int AcademyLevel
    {
        get => int.TryParse(GetMeta($"acadlvl_{CurrentTeamId}"), out var v) ? Math.Clamp(v, 1, 5) : 1;
        private set => SetMeta($"acadlvl_{CurrentTeamId}", value.ToString());
    }

    public long FacilityUpgradeCost(int currentLevel) => 2_000_000L * currentLevel;

    public string UpgradeTrainingGround()
    {
        var lvl = TrainingLevel;
        if (lvl >= 5) return "The training ground is already state of the art.";
        var cost = FacilityUpgradeCost(lvl);
        if (!Finances.TrySpendOnTransfer(cost, minBalanceAfter: 0))
            return $"Level {lvl + 1} costs £{cost:N0} — you have £{Finances.Balance:N0}.";
        AdjustBudget(-cost);
        TrainingLevel = lvl + 1;
        SyncBudget();
        PostInbox("Club", $"Training ground upgraded to level {lvl + 1}",
            "Better pitches, better recovery suites, better sessions — development across the " +
            "squad quickens from today.");
        return $"Training ground now level {lvl + 1} (£{cost:N0}).";
    }

    public string UpgradeAcademy()
    {
        var lvl = AcademyLevel;
        if (lvl >= 5) return "The academy is already elite.";
        var cost = FacilityUpgradeCost(lvl);
        if (!Finances.TrySpendOnTransfer(cost, minBalanceAfter: 0))
            return $"Level {lvl + 1} costs £{cost:N0} — you have £{Finances.Balance:N0}.";
        AdjustBudget(-cost);
        AcademyLevel = lvl + 1;
        SyncBudget();
        PostInbox("Club", $"Academy upgraded to level {lvl + 1}",
            "Sharper coaching and wider scouting nets at youth level — expect stronger intakes " +
            "from next summer.");
        return $"Academy now level {lvl + 1} (£{cost:N0}).";
    }

    /// <summary>Facility growth bonus: level 1 = ×1.0 … level 5 = ×1.4 on weekly development.</summary>
    internal double TrainingFacilityMultiplier => 1.0 + (TrainingLevel - 1) * 0.1;
}
