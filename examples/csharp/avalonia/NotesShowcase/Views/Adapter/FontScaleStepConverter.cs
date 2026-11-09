using System;
using System.Globalization;
using Avalonia.Data.Converters;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// View-side converter for the theme control strip (ADR-0201 §2.4). It adds
/// the step in <c>ConverterParameter</c> (for example <c>-0.1</c> or
/// <c>0.1</c>) to the bound font scale factor. The result is the
/// <c>CommandParameter</c> of <see cref="ViewModels.ThemeVM.SetFontScale"/>,
/// which clamps it. The converter keeps the view code-behind trivial.
/// </summary>
public sealed class FontScaleStepConverter : IValueConverter
{
    /// <inheritdoc/>
    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not double factor) return null;
        var step = parameter switch
        {
            double d => d,
            string s => double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture),
            _ => 0.0,
        };
        return factor + step;
    }

    /// <inheritdoc/>
    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}
