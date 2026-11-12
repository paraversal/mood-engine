import AppKit

/// The wallpaper row in the menu: thumbnail, author and source. It is a custom view
/// rather than an item image because NSMenu sizes its image column to the widest
/// image, so a large thumbnail would push every title sideways, and only for themes
/// that have a wallpaper.
final class WallpaperRowView: NSView {
    var onClick: (() -> Void)?

    private let thumb: NSImage?
    private let title: String
    private let detail: String
    private static let size = NSSize(width: 270, height: 60)

    init(wallpaper w: Status.Wallpaper) {
        thumb = NSImage(contentsOfFile: w.thumb)
        title = w.author.map { "by \($0)" } ?? w.source ?? w.key
        detail = [w.author == nil ? nil : w.source, w.pinned ? "pinned" : "today’s pick"]
            .compactMap { $0 }.joined(separator: " · ")
        super.init(frame: NSRect(origin: .zero, size: Self.size))
        autoresizingMask = [.width]
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    private var highlighted: Bool { enclosingMenuItem?.isHighlighted ?? false }

    override func draw(_ dirtyRect: NSRect) {
        let hl = highlighted
        if hl {
            NSColor.selectedContentBackgroundColor.setFill()
            NSBezierPath(roundedRect: bounds.insetBy(dx: 5, dy: 1), xRadius: 4, yRadius: 4).fill()
        }
        // Thumbnail, 16:9, filled and clipped to rounded corners.
        let box = NSRect(x: 14, y: 6, width: 85, height: 48)
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(roundedRect: box, xRadius: 4, yRadius: 4).addClip()
        if let img = thumb, img.size.width > 0, img.size.height > 0 {
            let scale = max(box.width / img.size.width, box.height / img.size.height)
            let w = img.size.width * scale, h = img.size.height * scale
            img.draw(in: NSRect(x: box.midX - w / 2, y: box.midY - h / 2, width: w, height: h),
                     from: .zero, operation: .sourceOver, fraction: 1)
        } else {
            NSColor.quaternaryLabelColor.setFill()
            box.fill()
        }
        NSGraphicsContext.restoreGraphicsState()
        NSColor.separatorColor.setStroke()
        let border = NSBezierPath(roundedRect: box.insetBy(dx: 0.25, dy: 0.25), xRadius: 4, yRadius: 4)
        border.lineWidth = 0.5
        border.stroke()

        let textX = box.maxX + 10
        let width = bounds.width - textX - 14
        let para = NSMutableParagraphStyle()
        para.lineBreakMode = .byTruncatingTail
        let main: [NSAttributedString.Key: Any] = [
            .font: NSFont.menuFont(ofSize: 0),
            .foregroundColor: hl ? NSColor.selectedMenuItemTextColor : NSColor.labelColor,
            .paragraphStyle: para,
        ]
        let small: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: hl ? NSColor.selectedMenuItemTextColor.withAlphaComponent(0.8)
                                 : NSColor.secondaryLabelColor,
            .paragraphStyle: para,
        ]
        (title as NSString).draw(in: NSRect(x: textX, y: 30, width: width, height: 18), withAttributes: main)
        (detail as NSString).draw(in: NSRect(x: textX, y: 13, width: width, height: 16), withAttributes: small)
    }

    // Menus deliver mouse events to item views while tracking; redraw on hover changes.
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                       owner: self, userInfo: nil))
    }

    override func mouseEntered(with event: NSEvent) { needsDisplay = true }
    override func mouseExited(with event: NSEvent) { needsDisplay = true }

    override func mouseUp(with event: NSEvent) {
        enclosingMenuItem?.menu?.cancelTracking()
        onClick?()
    }
}
