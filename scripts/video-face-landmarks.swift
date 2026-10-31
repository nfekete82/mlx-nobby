// Optional local CPU diagnostics; no network, model downloads or identity recognition.
// swiftc scripts/video-face-landmarks.swift -o /private/tmp/video-face-landmarks
import Foundation
import Vision
import AppKit

var output = [[String: Any]]()
for file in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: file)
    let request = VNDetectFaceLandmarksRequest()
    request.usesCPUOnly = true
    let handler = VNImageRequestHandler(url: url, options: [:])
    try handler.perform([request])
    var faces = [[String: Any]]()
    for face in request.results ?? [] {
        var landmarks = [String: [[Double]]]()
        if let features = face.landmarks {
            let regions: [(String, VNFaceLandmarkRegion2D?)] = [
                ("leftEye", features.leftEye), ("rightEye", features.rightEye),
                ("leftPupil", features.leftPupil), ("rightPupil", features.rightPupil),
                ("outerLips", features.outerLips), ("nose", features.nose),
                ("faceContour", features.faceContour)]
            for (name, region) in regions {
                if let region = region {
                    landmarks[name] = region.normalizedPoints.map { [Double($0.x), Double($0.y)] }
                }
            }
        }
        let rect = face.boundingBox
        // Convert normalized face width/height to pixels so Python can correct aspect ratio.
        guard let image = NSImage(contentsOf: url),
              let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            throw NSError(domain: "VideoDiagnostics", code: 1)
        }
        faces.append(["confidence": Double(face.confidence),
            "bounding_box": [rect.minX*Double(cg.width), rect.minY*Double(cg.height),
                             rect.width*Double(cg.width), rect.height*Double(cg.height)],
            "landmarks": landmarks,
            "yaw": face.yaw.map { $0.doubleValue } as Any? ?? NSNull(),
            "roll": face.roll.map { $0.doubleValue } as Any? ?? NSNull()])
    }
    output.append(["faces": faces, "request_revision": request.revision])
}
let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
