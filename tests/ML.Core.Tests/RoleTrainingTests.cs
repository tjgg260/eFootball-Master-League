using ML.Core.Development;
using ML.Core.Domain;

namespace ML.Core.Tests;

public class RoleTrainingTests
{
    [Fact]
    public void NaturalPositionIsPlayableAndOthersAreNot()
    {
        var gyokeres = new PlayerPositions(Position.CF);
        Assert.True(gyokeres.CanPlay(Position.CF));
        Assert.False(gyokeres.CanPlay(Position.SS));   // deep-lying forward: not trained
        Assert.Equal(Aptitude.Unfamiliar, gyokeres.AptitudeAt(Position.SS));
    }

    [Fact]
    public void CannotPlayAnUntrainedRoleUntilTrainingCompletes()
    {
        var p = new PlayerPositions(Position.CF);
        p.StartTraining(Position.SS);

        Assert.True(p.IsTraining(Position.SS));
        Assert.False(p.CanPlay(Position.SS));          // in training, still not selectable there

        for (var i = 0; i < PlayerPositions.SessionsToLearn - 1; i++)
        {
            p.RecordTrainingSession();
            Assert.False(p.CanPlay(Position.SS));       // not yet
        }

        var learned = p.RecordTrainingSession();        // final session
        Assert.Contains(Position.SS, learned);
        Assert.True(p.CanPlay(Position.SS));
        Assert.Equal(Aptitude.Competent, p.AptitudeAt(Position.SS));
    }

    [Fact]
    public void SecondaryPositionsAreImmediatelyPlayable()
    {
        var versatile = new PlayerPositions(Position.CMF, alsoCompetent: new[] { Position.DMF, Position.AMF });
        Assert.True(versatile.CanPlay(Position.CMF));
        Assert.True(versatile.CanPlay(Position.DMF));
        Assert.True(versatile.CanPlay(Position.AMF));
        Assert.False(versatile.CanPlay(Position.CF));
        Assert.Equal(3, versatile.PlayablePositions.Count);
    }

    [Fact]
    public void StoppingTrainingRevertsToUnfamiliar()
    {
        var p = new PlayerPositions(Position.CF);
        p.StartTraining(Position.RWF);
        p.RecordTrainingSession();
        p.StopTraining(Position.RWF);
        Assert.Equal(Aptitude.Unfamiliar, p.AptitudeAt(Position.RWF));
        Assert.Equal(0, p.TrainingProgress(Position.RWF));
    }

    [Fact]
    public void TrainingAnAlreadyCompetentRoleIsANoOp()
    {
        var p = new PlayerPositions(Position.CMF, alsoCompetent: new[] { Position.DMF });
        p.StartTraining(Position.DMF);
        Assert.False(p.IsTraining(Position.DMF));       // still just competent, not re-training
        Assert.True(p.CanPlay(Position.DMF));
    }
}
