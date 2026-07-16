FROM python@sha256:9bed8554e926c07c6f908841d5ee88c33e8df9236b191526bbce81a9062ab43a
LABEL org.galaxy.image.authority="inactive"
LABEL org.galaxy.image.roles="verifier"
COPY bootstrap/galaxy_launcher/activation_image_entrypoint.py /opt/galaxy/activation_image_entrypoint.py
WORKDIR /empty
USER 65532:65532
ENTRYPOINT ["/usr/bin/env","-i","/usr/local/bin/python3","-I","-S","/opt/galaxy/activation_image_entrypoint.py"]
CMD ["image-canary"]
