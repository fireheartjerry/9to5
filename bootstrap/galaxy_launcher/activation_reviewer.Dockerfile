FROM python@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
LABEL org.galaxy.image.authority="inactive"
LABEL org.galaxy.image.roles="reviewer"
COPY bootstrap/galaxy_launcher/activation_image_entrypoint.py /opt/galaxy/activation_image_entrypoint.py
COPY --chmod=0555 containers/galaxy/generated/galaxy-sha1dc /opt/galaxy/galaxy-sha1dc
WORKDIR /empty
USER 65532:65532
ENTRYPOINT ["/usr/bin/env","-i","/usr/local/bin/python3","-I","-S","/opt/galaxy/activation_image_entrypoint.py"]
CMD ["image-canary"]
