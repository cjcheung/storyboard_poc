import Foundation
import CoreImage
import Vision
let ctx = CIContext()
let det = CIDetector(ofType: CIDetectorTypeFace, context: ctx, options: [CIDetectorAccuracy: CIDetectorAccuracyHigh])!
func esc(_ s: String) -> String { s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") }
for path in CommandLine.arguments.dropFirst() {
    guard let img = CIImage(contentsOf: URL(fileURLWithPath: path)) else { print("{\"f\":\"\(esc(path))\",\"err\":1}"); continue }
    let W = img.extent.width, H = img.extent.height
    let faces = det.features(in: img, options: [CIDetectorSmile: true, CIDetectorEyeBlink: true]) as! [CIFaceFeature]
    let req = VNDetectFaceRectanglesRequest()
    try? VNImageRequestHandler(ciImage: img, options: [:]).perform([req])
    let obs = req.results ?? []
    var parts: [String] = []
    for f in faces {
        let b = f.bounds
        let cx = (b.midX - img.extent.minX) / W, cy = (b.midY - img.extent.minY) / H
        var yaw = "null"; var best = 1e9
        for o in obs {
            let bb = o.boundingBox
            let d = hypot(bb.midX - cx, bb.midY - cy)
            if d < best && d < 0.08 { best = d; yaw = String(format: "%.3f", o.yaw?.doubleValue ?? 0) }
        }
        parts.append(String(format: "{\"x\":%.3f,\"y\":%.3f,\"h\":%.3f,\"smile\":%@,\"blink\":%@,\"yaw\":%@}", cx, cy, b.height / H, f.hasSmile ? "true" : "false", (f.leftEyeClosed || f.rightEyeClosed) ? "true" : "false", yaw))
    }
    print("{\"f\":\"\(esc(path))\",\"faces\":[\(parts.joined(separator: ","))]}")
}
