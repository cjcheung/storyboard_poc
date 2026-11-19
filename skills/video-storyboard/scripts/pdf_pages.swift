// Render PDF pages to PNG with macOS PDFKit (no poppler needed).
//   swift scripts/pdf_pages.swift <file.pdf> <out_dir> [width_px=2000]   -> out_dir/page_1.png ...
import Foundation
import PDFKit
let a = CommandLine.arguments
guard a.count >= 3, let doc = PDFDocument(url: URL(fileURLWithPath: a[1])) else { print("usage: pdf_pages.swift file.pdf out_dir [width]"); exit(1) }
let width = a.count > 3 ? Double(a[3]) ?? 2000 : 2000
try? FileManager.default.createDirectory(atPath: a[2], withIntermediateDirectories: true)
for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i) else { continue }
    let b = page.bounds(for: .mediaBox); let scale = width / b.width
    let img = page.thumbnail(of: CGSize(width: b.width * scale, height: b.height * scale), for: .mediaBox)
    if let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
        try? png.write(to: URL(fileURLWithPath: "\(a[2])/page_\(i + 1).png"))
    }
}
print("rendered", doc.pageCount, "pages")
