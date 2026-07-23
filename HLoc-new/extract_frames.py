import cv2
import os


video_path = "try.mp4"

save_dir = "datasets/my_desk/mapping"

os.makedirs(save_dir, exist_ok=True)


cap = cv2.VideoCapture(video_path)

fps = cap.get(cv2.CAP_PROP_FPS)

# 每秒保存5张
save_fps = 5
interval = int(fps / save_fps)


frame_id = 0
save_id = 0


while True:

    ret, frame = cap.read()

    if not ret:
        break


    if frame_id % interval == 0:

        filename = f"{save_id:05d}.jpg"

        cv2.imwrite(
            os.path.join(save_dir, filename),
            frame
        )

        save_id += 1


    frame_id += 1


cap.release()

print("FPS:", fps)
print("Total saved:", save_id)
