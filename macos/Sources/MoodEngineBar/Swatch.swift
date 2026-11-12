import AppKit

enum Swatch {
    /// A small palette strip for menu items: the background with fg, accent and
    /// status colours on it.
    static func image(_ t: Status.Theme) -> NSImage {
        let colors = t.colors.map { $0.flatMap(color) }
        let bg = colors.first.flatMap { $0 } ?? .gray
        let dots = [2, 3, 4, 5, 6].compactMap { colors.indices.contains($0) ? colors[$0] : nil }
        let size = NSSize(width: 30, height: 16)
        let img = NSImage(size: size, flipped: false) { rect in
            let r = rect.insetBy(dx: 0.5, dy: 1.5)
            let box = NSBezierPath(roundedRect: r, xRadius: 3.5, yRadius: 3.5)
            bg.setFill()
            box.fill()
            NSColor.separatorColor.setStroke()
            box.lineWidth = 0.5
            box.stroke()
            let d: CGFloat = 4, gap: CGFloat = 1.3
            let total = CGFloat(dots.count) * d + CGFloat(max(dots.count - 1, 0)) * gap
            var x = r.midX - total / 2
            for c in dots {
                c.setFill()
                NSBezierPath(ovalIn: NSRect(x: x, y: r.midY - d / 2, width: d, height: d)).fill()
                x += d + gap
            }
            return true
        }
        return img
    }

    static func color(_ hex: String) -> NSColor? {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        return NSColor(srgbRed: CGFloat((v >> 16) & 0xff) / 255, green: CGFloat((v >> 8) & 0xff) / 255,
                       blue: CGFloat(v & 0xff) / 255, alpha: 1)
    }
}
