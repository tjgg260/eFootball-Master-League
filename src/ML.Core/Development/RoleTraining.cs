using ML.Core.Domain;

namespace ML.Core.Development;

/// <summary>
/// How well a player knows a position. Maps onto eFootball's 2-bit position aptitude (four
/// levels per position in Player.bin), so this is writable back to the game, not just app state.
/// </summary>
public enum Aptitude
{
    Unfamiliar = 0,   // cannot play the role
    InTraining = 1,   // learning it — not yet selectable there
    Competent = 2,    // trained: can be assigned the role
    Natural = 3,      // their natural position(s)
}

/// <summary>
/// A player's positional versatility and the training that changes it. The rule the user asked
/// for: you can only assign a role a player is trained for — <see cref="CanPlay"/> requires at
/// least <see cref="Aptitude.Competent"/>. To use a new role you must train it first, which
/// takes a number of sessions before it flips from InTraining to Competent.
/// </summary>
public sealed class PlayerPositions
{
    public const int SessionsToLearn = 6;

    private readonly Dictionary<Position, Aptitude> _aptitude = new();
    private readonly Dictionary<Position, int> _training = new();

    public PlayerPositions(Position natural, IEnumerable<Position>? alsoCompetent = null)
    {
        _aptitude[natural] = Aptitude.Natural;
        foreach (var p in alsoCompetent ?? Enumerable.Empty<Position>())
        {
            if (!_aptitude.ContainsKey(p))
            {
                _aptitude[p] = Aptitude.Competent;
            }
        }
    }

    public Aptitude AptitudeAt(Position position) =>
        _aptitude.TryGetValue(position, out var a) ? a : Aptitude.Unfamiliar;

    /// <summary>The gate: a player may only be assigned a role they are trained for.</summary>
    public bool CanPlay(Position position) => AptitudeAt(position) >= Aptitude.Competent;

    public IReadOnlyCollection<Position> PlayablePositions =>
        _aptitude.Where(kv => kv.Value >= Aptitude.Competent).Select(kv => kv.Key).ToList();

    public bool IsTraining(Position position) => AptitudeAt(position) == Aptitude.InTraining;

    /// <summary>Begin learning a role the player cannot yet play. No-op if already competent.</summary>
    public void StartTraining(Position position)
    {
        if (AptitudeAt(position) >= Aptitude.Competent)
        {
            return;
        }

        _aptitude[position] = Aptitude.InTraining;
        _training.TryAdd(position, 0);
    }

    public void StopTraining(Position position)
    {
        if (AptitudeAt(position) == Aptitude.InTraining)
        {
            _aptitude[position] = Aptitude.Unfamiliar;
            _training.Remove(position);
        }
    }

    public int TrainingProgress(Position position) =>
        _training.TryGetValue(position, out var n) ? n : 0;

    /// <summary>
    /// One training block (a matchday / week). Advances every in-training position; any that
    /// reach the threshold flip to Competent and become selectable. Returns positions newly
    /// learned this session so the inbox can announce them.
    /// </summary>
    public IReadOnlyList<Position> RecordTrainingSession()
    {
        var learned = new List<Position>();
        foreach (var position in _training.Keys.ToList())
        {
            _training[position]++;
            if (_training[position] >= SessionsToLearn)
            {
                _aptitude[position] = Aptitude.Competent;
                _training.Remove(position);
                learned.Add(position);
            }
        }
        return learned;
    }
}

/// <summary>Thrown when a lineup asks a player to fill a role they are not trained for.</summary>
public sealed class RoleNotTrainedException : InvalidOperationException
{
    public RoleNotTrainedException(PlayerId player, Position position)
        : base($"Player {player} is not trained to play {position}. Train the role first.")
    {
        Player = player;
        Position = position;
    }

    public PlayerId Player { get; }
    public Position Position { get; }
}
