---
source_url: https://www.fit.hcmus.edu.vn/tin-tuc/d/chuc-mung-sinh-vien-chuong-trinh-cu-nhan-tai-nang-cua-fithcmus-da-co-cong-bo-tren-hoi-nghi-uy-tin-quoc-te-nam-trong-top-20-cac-cong-bo-khoa-hoc-hang-dau-the-gioi-cua-nhom-nganh-computer-vision-pattern-recognition
site: fit
site_name: Khoa Công nghệ Thông tin
title: "Thông báo - Khoa Công Nghệ Thông Tin - Trường ĐH KHTN, ĐHQG-HCM"
fetched_at: 2026-11-09T00:18:59+07:00
sha256: 4ec5ffd4a75336351eb78867b15c7eea0b44e4dfdee60ed483f9d3fea9e71a5c
---

# Thông báo - Khoa Công Nghệ Thông Tin - Trường ĐH KHTN, ĐHQG-HCM

🌟 Tên bài báo: SAGA: Stable Acceleration Guidance for Autoregressive Video Generation
👉 Link bài báo: https://arxiv.org/abs/2607.08020
Các tác giả: Thanh-Nhan Vo, Trong-Thuan Nguyen, Trung-Hoang Le, Tam V. Nguyen, Minh-Triet Tran
- Sinh viên: Võ Thành Nhân (Cử nhân tài năng, 2023)
- GVHD: PGS. TS. Nguyễn Văn Tâm (Đại học Dayton, Hoa Kỳ) và P GS. TS. Trần Minh Triết, TS. Lê Trung Hoàng, ThS. Nguyễn Trọng Thuận (Trường Đại học Khoa học tự nhiên, ĐHQG-HCM)
🔥 Tóm tắt bài báo: Các mô hình khuếch tán video tự hồi quy (autoregressive video diffusion) cho phép sinh video hiệu quả theo dạng luồng và mở rộng tới các chuỗi dài. Tuy nhiên, do các biểu diễn ẩn (latent) đã sinh tiếp tục được sử dụng làm ngữ cảnh nhân quả (causal context) cho các bước tiếp theo, sai số có thể tích lũy dần theo thời gian và dẫn đến hiện tượng nhấp nháy, chuyển động giật hoặc sai lệch cấu trúc.
Để giải quyết vấn đề này, bài báo đề xuất SAGA, một phương pháp không cần huấn luyện lại (training-free) khai thác gia tốc rời rạc trong không gian ẩn (discrete latent acceleration) nhằm làm lộ rõ và kiểm soát các dao động cao tần gây mất ổn định. SAGA kết hợp nhiễu tự hồi quy có cấu trúc (structured autoregressive noise) để duy trì tương quan theo thời gian ngay từ bước khởi tạo với dẫn hướng phổ (spectral guidance) dựa trên Slepian/DPSS nhằm hạn chế các thành phần tần số cao trong miền gia tốc.
Nhờ hoạt động hoàn toàn tại thời điểm suy luận (inference time), SAGA có thể tích hợp trực tiếp vào các mô hình khuếch tán video tự hồi quy hiện có mà không cần huấn luyện lại hay thay đổi kiến trúc nền (backbone), qua đó hướng tới khả năng sinh video dài ổn định và nhất quán hơn theo thời gian.
✨ Điểm nổi bật của bài báo: SAGA tiếp cận vấn đề bất ổn theo thời gian (temporal instability) trong bài toán tạo video từ một góc nhìn khá mới. Thay vì trực tiếp làm mượt khung hình (frame) hay quỹ đạo biểu diễn ẩn (latent trajectory), phương pháp tập trung vào phân tích động học bậc hai trong không gian ẩn (latent space) thông qua gia tốc rời rạc (discrete latent acceleration). Ý tưởng cốt lõi là các dao động cao tần gây ra hiện tượng nhấp nháy, chuyển động giật và sai lệch cấu trúc sẽ được bộc lộ rõ hơn khi quan sát trong miền gia tốc, từ đó giúp mô hình nhận diện và kiểm soát những bất ổn tích lũy theo thời gian hiệu quả hơn.
Dựa trên quan sát này, SAGA kết hợp nhiễu tự hồi quy có cấu trúc (structured autoregressive noise) để kiểm soát tính tương quan theo thời gian ngay từ bước khởi tạo, cùng với dẫn hướng phổ (spectral guidance) trong miền gia tốc nhằm hạn chế các thành phần tần số cao gây mất ổn định. Toàn bộ cơ chế hoạt động tại thời điểm suy luận, vì vậy không cần huấn luyện lại mô hình và cũng không yêu cầu thay đổi kiến trúc nền.
Một điểm đáng chú ý khác là SAGA có tính cắm và chạy (plug-and-play), cho phép tích hợp trực tiếp vào nhiều mô hình khuếch tán video tự hồi quy (autoregressive video diffusion models) hiện có. Nhờ đó, phương pháp đặc biệt phù hợp với bài toán sinh video thời lượng dài, nơi sai số từ các khung hình trước có xu hướng tích lũy dần và làm suy giảm tính nhất quán của video theo thời gian.
🌈 Về Hội nghị Asian Conference on Computer Vision: https://scholar.google.com/citations?view_op=top_venues&hl=en&vq=eng_computervisionpatternrecognition
ACCV là một trong những hội nghị quốc tế uy tín và lâu đời của cộng đồng Computer Vision & Pattern Recognition, được tổ chức hai năm một lần dưới sự bảo trợ của Asian Federation of Computer Vision (AFCV). Theo Google Scholar Metrics, ACCV nằm trong Top 20 các publication venues hàng đầu thế giới trong nhóm Computer Vision & Pattern Recognition , xếp hạng 17, với h5-index 52 và h5-median 81.
ACCV 2026 diễn ra từ 14–18/12/2026 tại Osaka, Nhật Bản, quy tụ các công trình nghiên cứu tiên tiến trong nhiều hướng trọng điểm của Computer Vision hiện đại như generative models, video analysis, vision-language, 3D vision, autonomous driving, deep learning for computer vision và nhiều lĩnh vực liên quan.
🌻 Xin chúc mừng nhóm tác giả với những thành tựu nghiên cứu nổi bật này.
🌻Chúc các bạn sẽ tiếp tục đạt được thành công trong tương lai.
