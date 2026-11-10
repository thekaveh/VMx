using System.ComponentModel;
using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// Supporting cases for COL-072 (spec/21 §2.5, ADR-0220): a key-view facade
/// runs each of its own handlers, and a serviced collection's overridden
/// <c>PropertyChanged</c> event still removes a handler.
/// </summary>
public class CollectionNotificationFailureTests
{
    private sealed class HandlerFailure() : Exception("handler failed");

    [Fact]
    public void ReadOnlyObservableList_Throwing_Handler_Reaches_Later_Facade_Handlers()
    {
        var dict = new ObservableDictionary<string, int, string>();
        var later = 0;
        dict.Keys1.ItemAdded += (_, _) => throw new HandlerFailure();
        dict.Keys1.ItemAdded += (_, _) => later++;

        dict.Invoking(d => d.Add("a", 1, "v")).Should().Throw<HandlerFailure>();

        later.Should().Be(1);
    }

    [Fact]
    public void Serviced_PropertyChanged_Handler_Can_Be_Removed()
    {
        var collection = new ServicedObservableCollection<string>();
        var seen = 0;
        PropertyChangedEventHandler handler = (_, _) => seen++;
        INotifyPropertyChanged notifier = collection;
        notifier.PropertyChanged += handler;
        collection.Add("a");
        notifier.PropertyChanged -= handler;
        collection.Add("b");

        seen.Should().Be(2, "Add raises Count and Item[] once, before the handler is removed");
    }
}
