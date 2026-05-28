using FluentAssertions;
using VMx.Extensions;
using Xunit;

namespace VMx.Tests.Extensions;

public class LinqHelpersTests
{
    private static readonly int[] _twoThreeFour = [2, 3, 4];
    private static readonly int[] _seven = [7];
    private static readonly int[] _oneZeroFour = [1, 2, 0, 4];

    // --------------------------------------------------------------------
    // CartesianProduct
    // --------------------------------------------------------------------

    [Fact]
    public void CartesianProduct_Two_Sequences_Correct_Count()
    {
        var a = new[] { 1, 2 };
        var b = new[] { "a", "b", "c" };
        var result = LinqHelpers.CartesianProduct(a, b).ToList();
        result.Should().HaveCount(6);
    }

    [Fact]
    public void CartesianProduct_Two_Sequences_Correct_Pairs()
    {
        var a = new[] { 1, 2 };
        var b = new[] { "a", "b", "c" };
        var result = LinqHelpers.CartesianProduct(a, b).ToList();
        result.Should().Contain(new[] { (1, "a"), (1, "b"), (1, "c"), (2, "a"), (2, "b"), (2, "c") });
    }

    [Fact]
    public void CartesianProduct_Empty_A_Returns_Empty()
    {
        var a = Array.Empty<int>();
        var b = new[] { "x" };
        LinqHelpers.CartesianProduct(a, b).Should().BeEmpty();
    }

    [Fact]
    public void CartesianProduct_Empty_B_Returns_Empty()
    {
        var a = new[] { 1 };
        var b = Array.Empty<string>();
        LinqHelpers.CartesianProduct(a, b).Should().BeEmpty();
    }

    // --------------------------------------------------------------------
    // Sample
    // --------------------------------------------------------------------

    [Fact]
    public void Sample_Every_Third_Element()
    {
        var seq = new[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 };
        seq.Sample(3).Should().Equal(1, 4, 7, 10);
    }

    [Fact]
    public void Sample_Every_One_Returns_All()
    {
        var seq = new[] { 1, 2, 3 };
        seq.Sample(1).Should().Equal(1, 2, 3);
    }

    [Fact]
    public void Sample_Larger_Than_Length_Returns_First()
    {
        var seq = new[] { 5, 6, 7 };
        seq.Sample(10).Should().Equal(5);
    }

    [Fact]
    public void Sample_Zero_Every_Throws()
    {
        var seq = new[] { 1, 2, 3 };
        var act = () => seq.Sample(0).ToList();
        act.Should().Throw<ArgumentOutOfRangeException>();
    }

    // --------------------------------------------------------------------
    // Product
    // --------------------------------------------------------------------

    [Fact]
    public void Product_Multiplies_All_Elements()
    {
        _twoThreeFour.Product().Should().Be(24);
    }

    [Fact]
    public void Product_Single_Element_Returns_That_Element()
    {
        _seven.Product().Should().Be(7);
    }

    [Fact]
    public void Product_Of_Empty_Returns_One()
    {
        Enumerable.Empty<int>().Product().Should().Be(1);
    }

    [Fact]
    public void Product_With_Zero_Returns_Zero()
    {
        _oneZeroFour.Product().Should().Be(0);
    }
}
