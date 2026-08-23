using ML.Core;
using ML.Core.Management;
using ML.Core.Selection;
using ML.Data;

namespace ML.App;

public sealed record NegotiationView(
    long PlayerId, string PlayerName, string SellerName, int Round, long Ask, string State,
    long MarketValue, string Stance);

/// <summary>
/// Transfer negotiation v2 (P5): multi-round talks with the SELLING CLUB — fee, sell-on,
/// instalments — then the agent's wage step, then a real contract for the signing. Pure
/// rules in ML.Core.Management.ClubNegotiation; this partial owns persistence and money.
/// Sell-on clauses are stored and actually pay out when the player moves on.
/// </summary>
public sealed partial class Session
{
    // ------------------------------------------------------------------ open/read

    public NegotiationView? NegotiationFor(long playerId)
    {
        using var q = Db.Connection.CreateCommand();
        q.CommandText = "SELECT seller_id, round, ask, state FROM negotiations WHERE player_id=$p";
        q.Parameters.AddWithValue("$p", playerId);
        using var r = q.ExecuteReader();
        if (!r.Read()) return null;
        var (rating, age, name) = PlayerBasics(playerId);
        var value = MarketValueOf(playerId, rating, age);
        var sellerId = r.GetInt32(0);
        return new NegotiationView(playerId, name,
            sellerId == 0 ? "Free agent" : TeamName(sellerId),
            r.GetInt32(1), r.GetInt64(2), r.GetString(3), value,
            ClubNegotiation.Stance(r.GetInt64(2), 0, r.GetInt32(1)));
    }

    /// <summary>Open talks: the club states its ask (free agents skip straight to terms).</summary>
    public string StartNegotiation(long playerId)
    {
        if (!TransferWindowOpen()) return TransferWindowLabel() + ". No talks outside the window.";
        if (Repo.Squad(CurrentTeamId).Any(s => s.PlayerId == playerId))
            return "He is already your player.";
        var (rating, age, name) = PlayerBasics(playerId);
        var value = MarketValueOf(playerId, rating, age);
        var seller = OwningClub(playerId);
        if (seller is { } club && Repo.Squad(club.TeamId).Count <= 18)
            return $"{club.Name} won't discuss {name} — their squad is at the minimum.";

        var premium = (int)((uint)((playerId + SeasonId) * 2654435761) % 16) + 5;
        var difficulty = (GetMeta("transfer_difficulty") ?? "Normal") switch
        { "Easy" => 90, "Hard" => 115, _ => 100 };
        // FM-style willingness (P5): the target's squad status at HIS club scales the ask —
        // a Star Player costs a fortune, Surplus goes cheap and gladly.
        var status = seller is null ? "Squad Player" : PlayTimeStatusOf(playerId);
        var ask = seller is null ? value
            : ClubNegotiation.OpeningAsk(value, premium, difficulty) * StatusAskPct(status) / 100;
        // NOT FOR SALE (player_market.transfer_status): everyone has a price, but it's silly money
        // and the club opens hostile.
        var notForSale = false;
        using (var st = Db.Connection.CreateCommand())
        {
            st.CommandText = "SELECT transfer_status FROM player_market WHERE player_id=$p";
            st.Parameters.AddWithValue("$p", playerId);
            notForSale = st.ExecuteScalar() as string == "not-for-sale";
        }
        if (notForSale && seller is not null)
        {
            ask = ask * 22 / 10;
        }
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "INSERT INTO negotiations(player_id,seller_id,round,ask,state) " +
                          "VALUES($p,$s,1,$a,'open') ON CONFLICT(player_id) DO UPDATE SET " +
                          "seller_id=excluded.seller_id, round=1, ask=excluded.ask, state='open'";
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.Parameters.AddWithValue("$s", seller?.TeamId ?? 0);
        cmd.Parameters.AddWithValue("$a", ask);
        cmd.ExecuteNonQuery();
        return seller is { } c2
            ? (notForSale
                ? $"{c2.Name} insist {name} is NOT FOR SALE. They'd only even take a call at " +
                  $"£{ask:N0} — silly money."
                : $"{c2.Name} open talks over {name} ({status} there): they'd listen at about £{ask:N0}." +
                  (status == "Star Player" ? " They do NOT want to sell — expect a war."
                   : status == "Surplus to Requirements" ? " They want him gone — push hard." : ""))
            : $"{name} is a free agent — agree market value £{value:N0} plus his wages.";
    }

    // ------------------------------------------------------------------ the rounds

    public int DealLikelihood(long playerId, long fee, int sellOnPct, bool instalments)
    {
        var n = NegotiationFor(playerId);
        return n is null ? 0
            : ClubNegotiation.Likelihood(n.Ask, fee, sellOnPct, instalments, n.MarketValue);
    }

    /// <summary>One round: send the package, get accept / counter / the door.</summary>
    public (string Message, bool Agreed, bool Dead) SendClubOffer(
        long playerId, long fee, int sellOnPct, bool instalments)
    {
        var n = NegotiationFor(playerId);
        if (n is null || n.State != "open") return ("No open negotiation.", false, false);
        if (n.SellerName == "Free agent")
        {
            // Free agents have no club step — the fee is the market rate, then wages.
            if (fee < n.MarketValue)
                return ($"£{fee:N0} undervalues him — the market rate is £{n.MarketValue:N0}.", false, false);
            SetNegotiationState(playerId, "agreed");
            return ("He'll sign — agree his wages to complete.", true, false);
        }

        var (verdict, newAsk) = ClubNegotiation.Respond(
            n.Ask, fee, sellOnPct, instalments, n.MarketValue, n.Round);
        switch (verdict)
        {
            case ClubNegotiation.Verdict.Accepted:
                SetNegotiationState(playerId, "agreed");
                return ($"{n.SellerName} ACCEPT the package (£{fee:N0}" +
                        (sellOnPct > 0 ? $" + {sellOnPct}% sell-on" : "") +
                        (instalments ? ", in instalments" : "") +
                        ") — agree his wages to complete.", true, false);
            case ClubNegotiation.Verdict.WalkedAway:
                SetNegotiationState(playerId, "dead");
                PostInbox("Transfer", $"Talks collapse: {n.PlayerName}",
                    $"{n.SellerName} have ended negotiations. They will not reopen them this window.");
                return ($"{n.SellerName} walk away — talks are over this window.", false, true);
            default:
                using (var upd = Db.Connection.CreateCommand())
                {
                    upd.CommandText = "UPDATE negotiations SET round=round+1, ask=$a WHERE player_id=$p";
                    upd.Parameters.AddWithValue("$a", newAsk);
                    upd.Parameters.AddWithValue("$p", playerId);
                    upd.ExecuteNonQuery();
                }
                return ($"{n.SellerName} counter: they'd now do £{newAsk:N0}. " +
                        ClubNegotiation.Stance(newAsk, ClubNegotiation.EffectiveValue(
                            fee, sellOnPct, instalments, n.MarketValue), n.Round + 1),
                        false, false);
        }
    }

    public void WalkAwayFromNegotiation(long playerId) => SetNegotiationState(playerId, "dead");

    private void SetNegotiationState(long playerId, string state)
    {
        using var cmd = Db.Connection.CreateCommand();
        cmd.CommandText = "UPDATE negotiations SET state=$s WHERE player_id=$p";
        cmd.Parameters.AddWithValue("$s", state);
        cmd.Parameters.AddWithValue("$p", playerId);
        cmd.ExecuteNonQuery();
    }

    // ------------------------------------------------------------------ completion

    /// <summary>
    /// The wage step + the money + the paperwork: pays the agreed fee, writes a REAL
    /// contract (no more £500 stubs for signings), stores the sell-on clause, moves the
    /// player. Wage demand comes from the existing agent model.
    /// </summary>
    public string CompleteSigning(long playerId, long fee, int sellOnPct, bool instalments,
                                  long weeklyWage, int years)
    {
        var n = NegotiationFor(playerId);
        if (n is null || n.State != "agreed") return "No agreed deal to complete.";
        var (rating, age, name) = PlayerBasics(playerId);

        // The agent's floor: the real FM wage (or the model demand) with a modest deal-done discount.
        var demand = RealWageDemand(playerId, rating, age ?? 25, years) * 92 / 100;
        if (weeklyWage < demand)
            return $"His agent wants at least £{demand:N0}/wk on {years} years — £{weeklyWage:N0} won't do it.";

        var upfront = instalments ? fee / 2 : fee;
        if (!Finances.TrySpendOnTransfer(upfront, minBalanceAfter: 0))
            return $"You need £{upfront:N0} up front — you have £{Finances.Balance:N0}.";
        AdjustBudget(-upfront);
        if (instalments) SetMeta($"instalment_{playerId}_{SeasonId}", (fee - upfront).ToString());

        var seller = OwningClub(playerId);
        if (seller is { } club)
        {
            Repo.RemoveSquadMember(club.TeamId, playerId);
            using var pay = Db.Connection.CreateCommand();
            pay.CommandText = "UPDATE teams SET budget = budget + $f WHERE id=$t";
            pay.Parameters.AddWithValue("$f", upfront);
            pay.Parameters.AddWithValue("$t", club.TeamId);
            pay.ExecuteNonQuery();
            if (sellOnPct > 0) SetMeta($"sellon_{playerId}", $"{club.TeamId}:{sellOnPct}");
        }

        var squad = Repo.Squad(CurrentTeamId);
        var used = squad.Select(s => s.SquadNumber).ToHashSet();
        var shirt = Enumerable.Range(1, 99).FirstOrDefault(x => !used.Contains(x), 99);
        Repo.SetSquadMember(new SquadMemberRow
        { TeamId = CurrentTeamId, PlayerId = playerId, SquadNumber = shirt, Slot = squad.Count });

        using (var c = Db.Connection.CreateCommand())
        {
            c.CommandText = "INSERT INTO contracts(player_id,team_id,weekly_wage,expires_season) " +
                            "VALUES($p,$t,$w,$e) ON CONFLICT(player_id,team_id) DO UPDATE SET " +
                            "weekly_wage=$w, expires_season=$e";
            c.Parameters.AddWithValue("$p", playerId);
            c.Parameters.AddWithValue("$t", CurrentTeamId);
            c.Parameters.AddWithValue("$w", weeklyWage);
            c.Parameters.AddWithValue("$e", SeasonId + years);
            c.ExecuteNonQuery();
        }
        using (var t = Db.Connection.CreateCommand())
        {
            t.CommandText = "INSERT INTO transfers(player_id,from_team_id,to_team_id,fee,window,season_id) " +
                            "VALUES($p,$from,$t,$f,'negotiated',$s)";
            t.Parameters.AddWithValue("$p", playerId);
            t.Parameters.AddWithValue("$from", (object?)seller?.TeamId ?? DBNull.Value);
            t.Parameters.AddWithValue("$t", CurrentTeamId);
            t.Parameters.AddWithValue("$f", fee);
            t.Parameters.AddWithValue("$s", SeasonId);
            t.ExecuteNonQuery();
        }
        using (var del = Db.Connection.CreateCommand())
        {
            del.CommandText = "DELETE FROM negotiations WHERE player_id=$p";
            del.Parameters.AddWithValue("$p", playerId);
            del.ExecuteNonQuery();
        }
        _teamCache = null;
        _shooterPool = null;
        SyncBudget();
        var terms = $"£{fee:N0}" + (sellOnPct > 0 ? $" + {sellOnPct}% sell-on" : "") +
                    (instalments ? " (half now, half next summer)" : "");
        PostInbox("Transfer", $"Signed: {name}",
            $"{name} ({rating}) joins for {terms} on £{weeklyWage:N0}/wk × {years} years. Shirt {shirt}.",
            playerId: playerId);
        return $"DONE DEAL — {name} signs for {terms}, £{weeklyWage:N0}/wk × {years} yrs. Shirt {shirt}.";
    }

    /// <summary>The agent's asking wage for the UI's default (deal-done discount applied).</summary>
    public long SigningWageDemand(long playerId, int years)
    {
        var (rating, age, _) = PlayerBasics(playerId);
        return ContractNegotiation.WeeklyDemand(rating, age ?? 25, 60, years) * 92 / 100;
    }

    // ------------------------------------------------------------------ sell-on payouts

    /// <summary>When a player YOU sold with a sell-on moves again, the clause pays you.</summary>
    private void PaySellOnIfDue(long playerId, long fee)
    {
        if (GetMeta($"sellon_{playerId}") is not { } raw) return;
        var parts = raw.Split(':');
        if (parts.Length != 2 || !int.TryParse(parts[0], out var holder)
            || !int.TryParse(parts[1], out var pct)) return;
        if (holder != CurrentTeamId) return;
        var cut = fee * pct / 100;
        if (cut <= 0) return;
        Finances.ReceivePrize(cut);
        AdjustBudget(cut);
        SetMeta($"sellon_{playerId}", "");
        var name = PlayerNameOf(playerId);
        PostInbox("Transfer", $"Sell-on clause pays out: {name}",
            $"{name} has moved again — your {pct}% sell-on banks £{cut:N0}.", playerId: playerId);
    }

    // ------------------------------------------------------------------ deadline day (P5)

    public bool IsDeadlineDay()
    {
        var next = NextFixture();
        return next is not null && next.Kind == "league" && next.Matchday == 19
               && TransferWindowOpen();
    }

    /// <summary>
    /// Deadline-day drama, fired once when the window's last matchday approaches: a late
    /// premium bid for one of your best players, pressure on your open talks, and a busy
    /// ticker. Called from the weekly pass.
    /// </summary>
    public void RunDeadlineDay(int matchday)
    {
        if (matchday != 18 || GetMeta($"deadline_{SeasonId}") is not null) return;
        SetMeta($"deadline_{SeasonId}", "1");
        var rng = new SeededRandom((SeasonId * 17389 + 3) ^ WorldSeed);

        // A late premium bid for one of your top players (not the very best — the vultures circle
        // the second tier of your squad).
        var targets = Repo.SquadPlayers(CurrentTeamId)
            .OrderByDescending(p => p.OverallRating ?? 0).Skip(1).Take(3).ToList();
        if (targets.Count > 0)
        {
            var t = targets[rng.Next(targets.Count)];
            var buyer = Repo.Teams().Where(x => x.LeagueId is TopFlight or Division2
                                                && x.Id != CurrentTeamId).ToList();
            if (buyer.Count > 0)
            {
                var b = buyer[rng.Next(buyer.Count)];
                var fee = (long)(ValuationOf(t.OverallRating ?? 65, t.Age) * (1.25 + rng.Next(30) / 100.0));
                var offers = PendingOffers().ToList();
                offers.Add(new TransferOffer(t.Id, t.Name, b.Name, fee));
                SaveOffers(offers);
                PostInbox("Transfer", $"🚨 DEADLINE DAY: late bid for {t.Name}",
                    $"{b.Name} table £{fee:N0} — a 25%+ premium — with hours left in the window. " +
                    "Accept or reject on the Market screen before the deadline.", matchday, t.Id);
            }
        }

        // Pressure on your open negotiations: sellers soften or slam the door.
        using (var q = Db.Connection.CreateCommand())
        {
            q.CommandText = "SELECT player_id, ask FROM negotiations WHERE state='open' AND seller_id != 0";
            using var r = q.ExecuteReader();
            var open = new List<(int Pid, long Ask)>();
            while (r.Read()) open.Add((r.GetInt32(0), r.GetInt64(1)));
            foreach (var (pid, ask) in open)
            {
                var softens = rng.Next(2) == 0;
                using var upd = Db.Connection.CreateCommand();
                upd.CommandText = softens
                    ? "UPDATE negotiations SET ask = ask * 95 / 100 WHERE player_id=$p"
                    : "UPDATE negotiations SET state='dead' WHERE player_id=$p";
                upd.Parameters.AddWithValue("$p", pid);
                upd.ExecuteNonQuery();
                PostInbox("Transfer", softens
                        ? $"DEADLINE DAY: {PlayerNameOf(pid)}'s club blink"
                        : $"DEADLINE DAY: {PlayerNameOf(pid)} talks are OFF",
                    softens
                        ? $"With hours left they drop the ask 5% (now ~£{ask * 95 / 100:N0}). Close it or lose it."
                        : "The selling club pulled out at the deadline. It happens.", matchday);
            }
        }
    }
}
